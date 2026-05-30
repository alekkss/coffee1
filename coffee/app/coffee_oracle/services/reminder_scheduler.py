"""Планировщик автоматических ремайндеров неактивным пользователям.

Отправляет сообщения через 1, 3, 7 и 30 дней после последнего предсказания,
а также подписчикам, неактивным 7 дней. Текст и кнопки зависят от типа
подписки пользователя. Поддерживает отправку как в Telegram,
так и в MAX в зависимости от поля user.source.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import InlineKeyboardMarkup
    from coffee_oracle.max_bot.api_client import MaxApiClient

from coffee_oracle.bot import texts
from coffee_oracle.bot.keyboards import KeyboardManager
from coffee_oracle.max_bot.keyboards import MaxKeyboardManager
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.models import UserReminder
from coffee_oracle.database.repositories import ReminderRepository

logger = logging.getLogger(__name__)

# Интервал проверки: каждые 6 часов
CHECK_INTERVAL_SECONDS = 6 * 60 * 60

# Дни неактивности для обычных ремайндеров (все пользователи)
REGULAR_REMINDER_DAYS = (
    UserReminder.DAY_1,
    UserReminder.DAY_3,
    UserReminder.DAY_7,
    UserReminder.DAY_30,
)


def _is_subscriber(user) -> bool:
    """Проверка, является ли пользователь подписчиком.

    Подписчик — пользователь с типом подписки premium
    (с непросроченной датой) или vip.

    Args:
        user: Объект User из БД.

    Returns:
        True если пользователь имеет активную подписку.
    """
    sub_type = getattr(user, "subscription_type", "free") or "free"

    if sub_type == "vip":
        return True

    if sub_type == "premium":
        until = getattr(user, "subscription_until", None)
        if until and until > datetime.utcnow():
            return True

    return False


class ReminderScheduler:
    """Фоновый планировщик ремайндеров неактивным пользователям.

    Периодически проверяет пользователей, чья последняя активность
    (предсказание или регистрация) попадает в суточные диапазоны
    1, 3, 7 или 30 дней назад, и отправляет им мотивирующее сообщение
    с inline-кнопками. Отдельно проверяет подписчиков, неактивных 7 дней.
    Поддерживает мультиплатформенную отправку (Telegram/MAX).

    Args:
        bot: Экземпляр aiogram Bot для Telegram (опционально).
        max_api_client: HTTP-клиент MAX API (опционально).
    """

    def __init__(
        self,
        bot: Optional["Bot"] = None,
        max_api_client: Optional["MaxApiClient"] = None,
    ):
        self._bot = bot
        self._max_api_client = max_api_client
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Запуск цикла планировщика ремайндеров."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(), name="reminder_scheduler",
        )
        logger.info(
            "Планировщик ремайндеров запущен (интервал: %dс)",
            CHECK_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Остановка цикла планировщика."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Планировщик ремайндеров остановлен")

    async def _run_loop(self) -> None:
        """Основной цикл планировщика."""
        # Начальная задержка для полной инициализации приложения
        await asyncio.sleep(60)

        while self._running:
            try:
                await self._check_reminders()
            except Exception as e:
                logger.error(
                    "Ошибка планировщика ремайндеров: %s", e, exc_info=True,
                )

            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _check_reminders(self) -> None:
        """Проверка и отправка ремайндеров для всех типов."""
        logger.info("Проверка ремайндеров неактивности...")

        async for session in db_manager.get_session():
            reminder_repo = ReminderRepository(session)

            # Обычные ремайндеры (1, 3, 7, 30 дней) — для всех пользователей
            for day in REGULAR_REMINDER_DAYS:
                await self._process_regular_reminders(reminder_repo, day)

            # Специальный ремайндер для подписчиков, неактивных 7 дней
            await self._process_subscriber_reminders(reminder_repo)

    async def _process_regular_reminders(
        self,
        reminder_repo: ReminderRepository,
        day: int,
    ) -> None:
        """Обработка обычных ремайндеров для указанного дня.

        Args:
            reminder_repo: Репозиторий ремайндеров.
            day: День неактивности (1, 3, 7 или 30).
        """
        try:
            users = await reminder_repo.get_users_for_reminder(day)
            if not users:
                logger.debug("Ремайндер дня %d: пользователей не найдено", day)
                return

            logger.info(
                "Ремайндер дня %d: найдено %d пользователей", day, len(users),
            )

            for user in users:
                try:
                    await self._send_reminder(user, day)
                    await reminder_repo.mark_reminder_sent(user.id, day)
                except Exception as e:
                    logger.error(
                        "Ошибка отправки ремайндера дня %d "
                        "пользователю %d (source=%s): %s",
                        day, user.id, user.source, e,
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(
                "Ошибка обработки ремайндера дня %d: %s",
                day, e, exc_info=True,
            )

    async def _process_subscriber_reminders(
        self,
        reminder_repo: ReminderRepository,
    ) -> None:
        """Обработка ремайндеров для подписчиков, неактивных 7 дней."""
        try:
            users = await reminder_repo.get_subscribers_for_reminder()
            if not users:
                logger.debug(
                    "Ремайндер подписчиков (день %d): пользователей не найдено",
                    UserReminder.DAY_SUBSCRIBER_7,
                )
                return

            logger.info(
                "Ремайндер подписчиков (день %d): найдено %d пользователей",
                UserReminder.DAY_SUBSCRIBER_7, len(users),
            )

            for user in users:
                try:
                    await self._send_subscriber_reminder(user)
                    await reminder_repo.mark_reminder_sent(
                        user.id, UserReminder.DAY_SUBSCRIBER_7,
                    )
                except Exception as e:
                    logger.error(
                        "Ошибка отправки ремайндера подписчика "
                        "пользователю %d (source=%s): %s",
                        user.id, user.source, e,
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(
                "Ошибка обработки ремайндеров подписчиков: %s",
                e, exc_info=True,
            )

    async def _send_reminder(self, user, day: int) -> None:
        """Отправка ремайндера пользователю через правильный транспорт.

        Текст и клавиатура выбираются в зависимости от типа подписки
        пользователя: подписчики получают текст REMINDER_TEXT_SUBSCRIBER
        с 2 кнопками, free-пользователи — REMINDER_TEXT_FREE с 3 кнопками.

        Args:
            user: Объект User из БД.
            day: День неактивности (1, 3, 7 или 30).
        """
        is_sub = _is_subscriber(user)
        reminder_text = texts.REMINDER_TEXT_SUBSCRIBER if is_sub else texts.REMINDER_TEXT_FREE
        source = getattr(user, "source", "tg") or "tg"

        if source == "max":
            keyboard = (
                MaxKeyboardManager.get_reminder_keyboard_subscriber()
                if is_sub
                else MaxKeyboardManager.get_reminder_keyboard_free()
            )
            await self._notify_via_max(user.telegram_id, reminder_text, keyboard)
        else:
            keyboard = (
                KeyboardManager.get_reminder_keyboard_subscriber()
                if is_sub
                else KeyboardManager.get_reminder_keyboard_free()
            )
            await self._notify_via_telegram(user.telegram_id, reminder_text, keyboard)

    async def _send_subscriber_reminder(self, user) -> None:
        """Отправка ремайндера подписчику, неактивному 7 дней.

        Всегда использует текст и клавиатуру для подписчиков.

        Args:
            user: Объект User из БД (гарантированно подписчик).
        """
        reminder_text = texts.REMINDER_TEXT_SUBSCRIBER
        source = getattr(user, "source", "tg") or "tg"

        if source == "max":
            keyboard = MaxKeyboardManager.get_reminder_keyboard_subscriber()
            await self._notify_via_max(user.telegram_id, reminder_text, keyboard)
        else:
            keyboard = KeyboardManager.get_reminder_keyboard_subscriber()
            await self._notify_via_telegram(user.telegram_id, reminder_text, keyboard)

    async def _notify_via_telegram(
        self,
        telegram_id: int,
        text: str,
        reply_markup: Optional["InlineKeyboardMarkup"] = None,
    ) -> None:
        """Отправка ремайндера через Telegram.

        Args:
            telegram_id: Telegram user ID.
            text: Текст сообщения.
            reply_markup: Inline-клавиатура (опционально).
        """
        if not self._bot:
            logger.warning(
                "Не удалось отправить ремайндер пользователю TG %d: "
                "Telegram-бот не инициализирован",
                telegram_id,
            )
            return

        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=text,
                reply_markup=reply_markup,
            )
            logger.info("Ремайндер отправлен пользователю TG %d", telegram_id)
        except Exception as e:
            logger.warning(
                "Не удалось отправить ремайндер пользователю TG %d: %s",
                telegram_id, e,
            )

    async def _notify_via_max(
        self,
        max_user_id: int,
        text: str,
        keyboard: Optional[dict] = None,
    ) -> None:
        """Отправка ремайндера через MAX.

        Args:
            max_user_id: MAX user ID.
            text: Текст сообщения.
            keyboard: Вложение inline_keyboard (опционально).
        """
        if not self._max_api_client:
            logger.warning(
                "Не удалось отправить ремайндер пользователю MAX %d: "
                "MAX-бот не инициализирован",
                max_user_id,
            )
            return

        try:
            attachments = [keyboard] if keyboard else None
            await self._max_api_client.send_message(
                user_id=max_user_id,
                text=text,
                attachments=attachments,
            )
            logger.info("Ремайндер отправлен пользователю MAX %d", max_user_id)
        except Exception as e:
            logger.warning(
                "Не удалось отправить ремайндер пользователю MAX %d: %s",
                max_user_id, e,
            )
