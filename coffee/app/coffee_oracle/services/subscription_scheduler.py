"""Планировщик автопродления подписок.

Запускает фоновую задачу, которая периодически проверяет
истекающие подписки и либо автопродляет их через YooKassa API,
либо уведомляет пользователей. Поддерживает отправку уведомлений
на обе платформы: Telegram и MAX.
"""

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from coffee_oracle.max_bot.api_client import MaxApiClient

from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import SubscriptionRepository, SettingsRepository

logger = logging.getLogger(__name__)

# Интервал проверки: каждые 6 часов
CHECK_INTERVAL_SECONDS = 6 * 60 * 60

# За сколько дней до истечения пытаться продлить
RENEWAL_DAYS_BEFORE = 1


class SubscriptionScheduler:
    """Фоновый планировщик автопродления и уведомлений о подписках.

    Поддерживает отправку уведомлений пользователям обеих платформ
    (Telegram и MAX), определяя транспорт по полю source в записи
    пользователя.

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
        """Запуск цикла планировщика."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(), name="subscription_scheduler",
        )
        logger.info(
            "Планировщик подписок запущен (интервал: %dс)",
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
        logger.info("Планировщик подписок остановлен")

    async def _run_loop(self) -> None:
        """Основной цикл планировщика."""
        # Начальная задержка для полной инициализации приложения
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._check_expiring_subscriptions()
            except Exception as e:
                logger.error(
                    "Ошибка планировщика подписок: %s", e, exc_info=True,
                )

            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _check_expiring_subscriptions(self) -> None:
        """Поиск истекающих подписок и их обработка."""
        logger.info("Проверка истекающих подписок...")

        async for session in db_manager.get_session():
            sub_repo = SubscriptionRepository(session)
            settings_repo = SettingsRepository(session)

            # Получаем цену подписки для продления
            price_str = await settings_repo.get_setting("subscription_price")
            price = float(price_str) if price_str else 300.0

            # Находим пользователей с истекающими подписками
            expiring_users = await sub_repo.get_expiring_premium_users(
                days=RENEWAL_DAYS_BEFORE,
            )

            if not expiring_users:
                logger.info("Истекающих подписок не найдено")
                return

            logger.info(
                "Найдено %d истекающих подписок", len(expiring_users),
            )

            for user in expiring_users:
                try:
                    await self._process_expiring_user(
                        sub_repo, user, price,
                    )
                except Exception as e:
                    logger.error(
                        "Ошибка обработки истекающей подписки пользователя %d: %s",
                        user.id, e, exc_info=True,
                    )

    async def _process_expiring_user(
        self,
        sub_repo: SubscriptionRepository,
        user,
        price: float,
    ) -> None:
        """Обработка пользователя с истекающей подпиской.

        Если автопродление включено и есть сохранённый метод оплаты —
        пытается автосписание. Иначе — уведомляет о скором истечении.

        Args:
            sub_repo: Репозиторий подписок.
            user: Объект User из БД.
            price: Цена подписки в рублях.
        """
        recurring_enabled, charge_id = await sub_repo.is_recurring_enabled(user.id)

        if recurring_enabled and charge_id:
            # Попытка автопродления через YooKassa
            renewal_result = await self._attempt_auto_renewal(
                sub_repo, user, price, charge_id,
            )
            if renewal_result == "success":
                await self._notify_user_by_source(
                    user,
                    "✅ Подписка успешно продлена!\n\n"
                    f"Списано {price:.0f} ₽ за 1 месяц.\n"
                    "Спасибо за поддержку! ☕",
                )
                return
            elif renewal_result == "api_error":
                # Transient-ошибка — НЕ отключаем автопродление, повторим
                logger.warning(
                    "Transient API ошибка при автопродлении для пользователя %d; "
                    "повторим в следующем цикле",
                    user.id,
                )
                return
            else:
                # payment_declined — отключаем автопродление, уведомляем
                await sub_repo.disable_recurring_payment(user.id)
                await self._notify_user_by_source(
                    user,
                    "❌ Не удалось продлить подписку автоматически.\n\n"
                    "Возможно, на карте недостаточно средств.\n"
                    "Автопродление отключено.\n\n"
                    "Чтобы продлить вручную, используйте /subscribe",
                )
                return

        # Нет автопродления — просто уведомляем об истечении
        if user.subscription_until:
            until_str = user.subscription_until.strftime("%d.%m.%Y")
        else:
            until_str = "скоро"

        await self._notify_user_by_source(
            user,
            f"⏳ Ваша подписка истекает {until_str}!\n\n"
            "Чтобы продолжить пользоваться безлимитными гаданиями, "
            "продлите подписку.\n\n"
            "Используйте /subscribe для продления",
        )

    async def _attempt_auto_renewal(
        self,
        sub_repo: SubscriptionRepository,
        user,
        price: float,
        charge_id: str,
    ) -> str:
        """Попытка автопродления через сохранённый метод оплаты YooKassa.

        Returns:
            "success" — платёж прошёл, подписка продлена.
            "api_error" — transient-ошибка (5xx / timeout / сеть);
                          автопродление НЕ отключается.
            "payment_declined" — платёж отклонён или отменён;
                                  автопродление нужно отключить.
        """
        from coffee_oracle.services.payment_service import get_payment_service

        payment_service = get_payment_service()
        if not payment_service:
            logger.warning(
                "Невозможно автопродлить для пользователя %d: "
                "YooKassa не настроена",
                user.id,
            )
            return "api_error"

        price_kopecks = int(price * 100)
        label = payment_service.generate_payment_label(user.id)

        try:
            result = await payment_service.create_recurring_payment(
                amount=price_kopecks,
                description="Автопродление подписки Coffee Oracle",
                user_id=user.telegram_id,
                payment_method_id=charge_id,
                user_email=user.email,
            )

            if not result.get("success"):
                error_msg = result.get("error", "")
                logger.error(
                    "Ошибка автопродления для пользователя %d: %s",
                    user.id, error_msg,
                )
                if self._is_transient_api_error(result):
                    return "api_error"
                return "payment_declined"

            payment_id = result["payment_id"]

            # Polling с экспоненциальным backoff
            completed = await payment_service.wait_for_payment_completion(
                payment_id,
            )

            if completed:
                # Записываем платёж и продляем подписку
                await sub_repo.create_payment(
                    user_id=user.id,
                    amount=price_kopecks,
                    label=label,
                    payment_id=payment_id,
                    is_recurring=True,
                    recurring_charge_id=charge_id,
                )
                await sub_repo.update_payment_status(payment_id, "succeeded")
                await sub_repo.activate_premium(user.id, months=1)
                logger.info(
                    "Подписка автопродлена для пользователя %d", user.id,
                )
                return "success"
            else:
                logger.warning(
                    "Платёж автопродления %s не завершён для пользователя %d",
                    payment_id, user.id,
                )
                return "payment_declined"

        except Exception as e:
            logger.error(
                "Ошибка автопродления для пользователя %d: %s",
                user.id, e,
            )
            return "api_error"

    # ────────────────────────────────────────────
    #  Мультиплатформенная отправка уведомлений
    # ────────────────────────────────────────────

    async def _notify_user_by_source(self, user, text: str) -> None:
        """Отправка уведомления пользователю через правильный мессенджер.

        Определяет транспорт по значению user.source:
        - 'tg' → Telegram Bot API (aiogram)
        - 'max' → MAX Bot API (aiohttp)

        Args:
            user: Объект User из БД (содержит telegram_id и source).
            text: Текст уведомления.
        """
        source = getattr(user, "source", "tg") or "tg"
        platform_user_id = user.telegram_id

        if source == "max":
            await self._notify_via_max(platform_user_id, text)
        else:
            await self._notify_via_telegram(platform_user_id, text)

    async def _notify_via_telegram(self, telegram_id: int, text: str) -> None:
        """Отправка уведомления через Telegram.

        Args:
            telegram_id: Telegram user ID.
            text: Текст уведомления.
        """
        if not self._bot:
            logger.warning(
                "Не удалось уведомить пользователя TG %d: "
                "Telegram-бот не инициализирован",
                telegram_id,
            )
            return

        try:
            await self._bot.send_message(chat_id=telegram_id, text=text)
            logger.info(
                "Уведомление подписки отправлено пользователю TG %d",
                telegram_id,
            )
        except Exception as e:
            logger.warning(
                "Не удалось уведомить пользователя TG %d: %s",
                telegram_id, e,
            )

    async def _notify_via_max(self, max_user_id: int, text: str) -> None:
        """Отправка уведомления через MAX.

        Args:
            max_user_id: MAX user ID.
            text: Текст уведомления.
        """
        if not self._max_api_client:
            logger.warning(
                "Не удалось уведомить пользователя MAX %d: "
                "MAX-бот не инициализирован",
                max_user_id,
            )
            return

        try:
            await self._max_api_client.send_message(
                user_id=max_user_id,
                text=text,
            )
            logger.info(
                "Уведомление подписки отправлено пользователю MAX %d",
                max_user_id,
            )
        except Exception as e:
            logger.warning(
                "Не удалось уведомить пользователя MAX %d: %s",
                max_user_id, e,
            )

    @staticmethod
    def _is_transient_api_error(result: dict) -> bool:
        """Проверка, является ли ошибка временной (5xx / timeout / сеть).

        Временные ошибки НЕ приводят к отключению автопродления —
        планировщик повторит попытку в следующем цикле.

        Args:
            result: Результат вызова PaymentService.

        Returns:
            True, если ошибка временная.
        """
        error = result.get("error", "")
        # 5xx ошибки сервера
        if error.startswith("Server error"):
            return True
        # Ошибки таймаута
        if "timeout" in error.lower():
            return True
        # Код статуса в диапазоне 5xx
        status_code = result.get("status_code")
        if status_code is not None and status_code >= 500:
            return True
        # Сетевые ошибки (нет status_code и не известный 4xx паттерн)
        if status_code is None and not error.startswith("API error"):
            return True
        return False
