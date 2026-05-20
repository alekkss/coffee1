"""Планировщик автоматических ремайндеров неактивным пользователям.

Отправляет сообщения через 1, 3 и 7 дней после последнего предсказания,
чтобы вернуть пользователя в бот. Поддерживает отправку как в Telegram,
так и в MAX в зависимости от поля user.source.
"""

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from coffee_oracle.max_bot.api_client import MaxApiClient

from coffee_oracle.bot import texts
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import ReminderRepository

logger = logging.getLogger(__name__)

# Интервал проверки: каждые 6 часов
CHECK_INTERVAL_SECONDS = 6 * 60 * 60

# Дни неактивности, для которых отправляются ремайндеры
REMINDER_DAYS = (1, 3, 7)

# Соответствие дня тексту ремайндера
REMINDER_TEXTS = {
    1: texts.REMINDER_DAY_1,
    3: texts.REMINDER_DAY_3,
    7: texts.REMINDER_DAY_7,
}


class ReminderScheduler:
    """Фоновый планировщик ремайндеров неактивным пользователям.

    Периодически проверяет пользователей, чья последняя активность
    (предсказание или регистрация) попадает в суточные диапазоны
    1, 3 или 7 дней назад, и отправляет им мотивирующее сообщение.
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
        """Проверка и отправка ремайндеров для всех дней."""
        logger.info("Проверка ремайндеров неактивности...")

        async for session in db_manager.get_session():
            reminder_repo = ReminderRepository(session)

            for day in REMINDER_DAYS:
                try:
                    users = await reminder_repo.get_users_for_reminder(day)
                    if not users:
                        logger.debug("Ремайндер дня %d: пользователей не найдено", day)
                        continue

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

    async def _send_reminder(self, user, day: int) -> None:
        """Отправка ремайндера пользователю через правильный транспорт.

        Args:
            user: Объект User из БД.
            day: День неактивности (1, 3 или 7).
        """
        text = REMINDER_TEXTS.get(day, texts.REMINDER_DAY_1)
        source = getattr(user, "source", "tg") or "tg"

        if source == "max":
            await self._notify_via_max(user.telegram_id, text)
        else:
            await self._notify_via_telegram(user.telegram_id, text)

    async def _notify_via_telegram(self, telegram_id: int, text: str) -> None:
        """Отправка ремайндера через Telegram.

        Args:
            telegram_id: Telegram user ID.
            text: Текст сообщения.
        """
        if not self._bot:
            logger.warning(
                "Не удалось отправить ремайндер пользователю TG %d: "
                "Telegram-бот не инициализирован",
                telegram_id,
            )
            return

        try:
            await self._bot.send_message(chat_id=telegram_id, text=text)
            logger.info("Ремайндер отправлен пользователю TG %d", telegram_id)
        except Exception as e:
            logger.warning(
                "Не удалось отправить ремайндер пользователю TG %d: %s",
                telegram_id, e,
            )

    async def _notify_via_max(self, max_user_id: int, text: str) -> None:
        """Отправка ремайндера через MAX.

        Args:
            max_user_id: MAX user ID.
            text: Текст сообщения.
        """
        if not self._max_api_client:
            logger.warning(
                "Не удалось отправить ремайндер пользователю MAX %d: "
                "MAX-бот не инициализирован",
                max_user_id,
            )
            return

        try:
            await self._max_api_client.send_message(
                user_id=max_user_id,
                text=text,
            )
            logger.info("Ремайндер отправлен пользователю MAX %d", max_user_id)
        except Exception as e:
            logger.warning(
                "Не удалось отправить ремайндер пользователю MAX %d: %s",
                max_user_id, e,
            )