"""Обработчик вебхуков YooKassa.

Обрабатывает уведомления об оплате и активирует/деактивирует
подписки. Поддерживает отправку уведомлений пользователям
обеих платформ: Telegram и MAX.
"""

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from coffee_oracle.max_bot.api_client import MaxApiClient

from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import SubscriptionRepository, UserRepository

logger = logging.getLogger(__name__)

# IP-диапазоны YooKassa для валидации вебхуков
# https://yookassa.ru/developers/using-api/webhooks#ip
YOOKASSA_IP_RANGES = [
    "185.71.76.",
    "185.71.77.",
    "77.75.153.",
    "77.75.156.",
    "77.75.157.",
    "77.75.158.",
    "77.75.159.",
    "2a02:5180::",  # IPv6
]


def is_yookassa_ip(ip: str) -> bool:
    """Проверка принадлежности IP-адреса к диапазонам YooKassa.

    Args:
        ip: IP-адрес отправителя вебхука.

    Returns:
        True, если IP принадлежит YooKassa.
    """
    if not ip:
        return False
    for prefix in YOOKASSA_IP_RANGES:
        if ip.startswith(prefix):
            return True
    return False


class WebhookHandler:
    """Обработчик вебхуков YooKassa с мультиплатформенными уведомлениями.

    Определяет платформу пользователя (Telegram или MAX) по полю source
    в метаданных платежа или в записи пользователя в БД, и отправляет
    уведомления через соответствующий транспорт.

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

    async def handle_notification(self, event_type: str, payload: dict) -> dict:
        """Маршрутизация вебхука к соответствующему обработчику.

        Args:
            event_type: Тип события YooKassa (например, 'payment.succeeded').
            payload: Объект 'object' из тела вебхука.

        Returns:
            Словарь с результатом обработки.
        """
        handlers = {
            "payment.succeeded": self._handle_payment_succeeded,
            "payment.canceled": self._handle_payment_canceled,
            "refund.succeeded": self._handle_refund_succeeded,
        }

        handler = handlers.get(event_type)
        if not handler:
            logger.info("Игнорируем необработанное событие вебхука: %s", event_type)
            return {"ok": True, "message": f"Event {event_type} ignored"}

        try:
            return await handler(payload)
        except Exception as e:
            logger.error(
                "Ошибка обработчика вебхука для %s: %s",
                event_type, e, exc_info=True,
            )
            return {"ok": False, "message": str(e)}

    async def _handle_payment_succeeded(self, payment: dict) -> dict:
        """Обработка успешного платежа — активация подписки.

        Определяет платформу пользователя из metadata.source,
        находит пользователя в БД и активирует premium-подписку.
        Уведомление отправляется через соответствующий мессенджер.

        Args:
            payment: Объект платежа из вебхука YooKassa.

        Returns:
            Результат обработки.
        """
        payment_id = payment.get("id")
        metadata = payment.get("metadata", {})
        user_id_str = metadata.get("user_id")
        source = metadata.get("source", "tg")

        if not payment_id or not user_id_str:
            logger.warning(
                "Вебхук payment.succeeded: отсутствует id или user_id: %s",
                payment,
            )
            return {"ok": False, "message": "Missing payment_id or user_id in metadata"}

        platform_user_id = int(user_id_str)

        # Проверяем, сохранён ли метод оплаты (для рекуррентов)
        payment_method = payment.get("payment_method", {})
        method_saved = payment_method.get("saved", False)
        method_id = payment_method.get("id")

        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            sub_repo = SubscriptionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(
                platform_user_id, source=source,
            )
            if not db_user:
                logger.warning(
                    "Вебхук: пользователь не найден: platform_id=%s, source=%s",
                    user_id_str, source,
                )
                return {"ok": False, "message": "User not found"}

            # Идемпотентность: проверяем, не обработан ли уже этот платёж
            existing = await sub_repo.get_payment_by_payment_id(payment_id)
            if existing and existing.status in ("completed", "succeeded"):
                logger.info(
                    "Вебхук: платёж %s уже обработан, пропускаем",
                    payment_id,
                )
                return {"ok": True, "message": "Already processed"}

            # Активация premium
            await sub_repo.activate_premium(db_user.id, months=1)

            # Обновление статуса платежа в БД
            await sub_repo.update_payment_status(payment_id, "succeeded")

            # Включение автопродления, если метод оплаты сохранён
            if method_saved and method_id:
                await sub_repo.enable_recurring_payment(db_user.id, method_id)

            # Очистка in-memory pending-платежа
            from coffee_oracle.services.payment_service import get_payment_service
            ps = get_payment_service()
            if ps:
                ps.clear_pending_payment(platform_user_id)

            # Формируем текст уведомления
            recurring_msg = ""
            if method_saved:
                recurring_msg = "\n🔄 Автопродление включено."

            notification_text = (
                "✅ Оплата прошла успешно!\n\n"
                "Премиум-подписка активирована на 1 месяц.\n"
                f"Спасибо за поддержку! ☕{recurring_msg}"
            )

            # Отправляем уведомление через правильный мессенджер
            await self._notify_user_by_source(
                platform_user_id=platform_user_id,
                source=source,
                text=notification_text,
            )

            logger.info(
                "Вебхук: premium активирован для пользователя %d "
                "(source=%s, payment=%s)",
                db_user.id, source, payment_id,
            )
            return {"ok": True, "message": "Subscription activated"}

    async def _handle_payment_canceled(self, payment: dict) -> dict:
        """Обработка отменённого платежа.

        Args:
            payment: Объект платежа из вебхука YooKassa.

        Returns:
            Результат обработки.
        """
        payment_id = payment.get("id")
        metadata = payment.get("metadata", {})
        user_id_str = metadata.get("user_id")
        source = metadata.get("source", "tg")

        if not payment_id:
            return {"ok": False, "message": "Missing payment_id"}

        async for session in db_manager.get_session():
            sub_repo = SubscriptionRepository(session)
            await sub_repo.update_payment_status(payment_id, "canceled")

        # Очистка pending-платежа и уведомление
        if user_id_str:
            platform_user_id = int(user_id_str)

            from coffee_oracle.services.payment_service import get_payment_service
            ps = get_payment_service()
            if ps:
                ps.clear_pending_payment(platform_user_id)

            await self._notify_user_by_source(
                platform_user_id=platform_user_id,
                source=source,
                text=(
                    "❌ Платёж отменён.\n"
                    "Если хотите оформить подписку, используйте /subscribe"
                ),
            )

        logger.info("Вебхук: платёж %s отменён", payment_id)
        return {"ok": True, "message": "Payment canceled"}

    async def _handle_refund_succeeded(self, refund: dict) -> dict:
        """Обработка успешного возврата — логирование.

        Args:
            refund: Объект возврата из вебхука YooKassa.

        Returns:
            Результат обработки.
        """
        refund_id = refund.get("id")
        payment_id = refund.get("payment_id")
        logger.info(
            "Вебхук: возврат %s выполнен для платежа %s",
            refund_id, payment_id,
        )
        return {"ok": True, "message": "Refund noted"}

    # ────────────────────────────────────────────
    #  Мультиплатформенная отправка уведомлений
    # ────────────────────────────────────────────

    async def _notify_user_by_source(
        self,
        platform_user_id: int,
        source: str,
        text: str,
    ) -> None:
        """Отправка уведомления пользователю через правильный мессенджер.

        Определяет транспорт по значению source:
        - 'tg' → Telegram Bot API (aiogram)
        - 'max' → MAX Bot API (aiohttp)

        Args:
            platform_user_id: ID пользователя на платформе.
            source: Платформа ('tg' или 'max').
            text: Текст уведомления.
        """
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
                "Уведомление отправлено пользователю TG %d через Telegram",
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
                "Уведомление отправлено пользователю MAX %d через MAX API",
                max_user_id,
            )
        except Exception as e:
            logger.warning(
                "Не удалось уведомить пользователя MAX %d: %s",
                max_user_id, e,
            )
