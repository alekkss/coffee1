"""YooKassa webhook handler.

Processes payment notifications from YooKassa and activates/deactivates
subscriptions accordingly. This replaces the need for polling in most cases.

YooKassa sends POST requests with JSON body containing payment events.
Docs: https://yookassa.ru/developers/using-api/webhooks
"""

import logging
from typing import Optional

from aiogram import Bot

from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import SubscriptionRepository, UserRepository

logger = logging.getLogger(__name__)

# YooKassa sends webhooks from these IP ranges
# https://yookassa.ru/developers/using-api/webhooks#ip
YOOKASSA_IP_RANGES = [
    "185.71.76.",
    "185.71.77.",
    "77.75.153.",
    "77.75.156.",
    "77.75.157.",
    "77.75.158.",
    "77.75.159.",
    "2a02:5180::",  # IPv6 range
]


def is_yookassa_ip(ip: str) -> bool:
    """Check if the request IP belongs to YooKassa."""
    if not ip:
        return False
    for prefix in YOOKASSA_IP_RANGES:
        if ip.startswith(prefix):
            return True
    return False


class WebhookHandler:
    """Handles YooKassa webhook notifications."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def handle_notification(self, event_type: str, payload: dict) -> dict:
        """Route webhook notification to the appropriate handler.

        Args:
            event_type: YooKassa event type (e.g. 'payment.succeeded').
            payload: The 'object' field from the webhook body.

        Returns:
            dict with 'ok' and optional 'message'.
        """
        handlers = {
            "payment.succeeded": self._handle_payment_succeeded,
            "payment.canceled": self._handle_payment_canceled,
            "refund.succeeded": self._handle_refund_succeeded,
        }

        handler = handlers.get(event_type)
        if not handler:
            logger.info("Ignoring unhandled webhook event: %s", event_type)
            return {"ok": True, "message": f"Event {event_type} ignored"}

        try:
            return await handler(payload)
        except Exception as e:
            logger.error("Webhook handler error for %s: %s", event_type, e, exc_info=True)
            return {"ok": False, "message": str(e)}

    async def _handle_payment_succeeded(self, payment: dict) -> dict:
        """Process a successful payment — activate subscription."""
        payment_id = payment.get("id")
        metadata = payment.get("metadata", {})
        user_id_str = metadata.get("user_id")
        payment_type = metadata.get("type", "")

        if not payment_id or not user_id_str:
            logger.warning("Webhook payment.succeeded missing id or user_id: %s", payment)
            return {"ok": False, "message": "Missing payment_id or user_id in metadata"}

        telegram_user_id = int(user_id_str)

        # Check if payment method was saved (for recurring)
        payment_method = payment.get("payment_method", {})
        method_saved = payment_method.get("saved", False)
        method_id = payment_method.get("id")

        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            sub_repo = SubscriptionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(telegram_user_id)
            if not db_user:
                logger.warning("Webhook: user not found for telegram_id=%s", telegram_user_id)
                return {"ok": False, "message": "User not found"}

            # Idempotency: check if already processed
            existing = await sub_repo.get_payment_by_payment_id(payment_id)
            if existing and existing.status in ("completed", "succeeded"):
                logger.info("Webhook: payment %s already processed, skipping", payment_id)
                return {"ok": True, "message": "Already processed"}

            # Activate premium
            await sub_repo.activate_premium(db_user.id, months=1)

            # Update payment record status
            await sub_repo.update_payment_status(payment_id, "succeeded")

            # Enable recurring if payment method was saved
            if method_saved and method_id:
                await sub_repo.enable_recurring_payment(db_user.id, method_id)

            # Clear in-memory pending payment
            from coffee_oracle.services.payment_service import get_payment_service
            ps = get_payment_service()
            if ps:
                ps.clear_pending_payment(telegram_user_id)

            # Notify user
            recurring_msg = ""
            if method_saved:
                recurring_msg = "\n🔄 Автопродление включено."

            await self._notify_user(
                telegram_user_id,
                "✅ Оплата прошла успешно!\n\n"
                "Премиум-подписка активирована на 1 месяц.\n"
                f"Спасибо за поддержку! ☕{recurring_msg}",
            )

            logger.info(
                "Webhook: activated premium for user %d (payment %s)",
                db_user.id, payment_id,
            )
            return {"ok": True, "message": "Subscription activated"}

    async def _handle_payment_canceled(self, payment: dict) -> dict:
        """Process a canceled payment."""
        payment_id = payment.get("id")
        metadata = payment.get("metadata", {})
        user_id_str = metadata.get("user_id")

        if not payment_id:
            return {"ok": False, "message": "Missing payment_id"}

        async for session in db_manager.get_session():
            sub_repo = SubscriptionRepository(session)
            await sub_repo.update_payment_status(payment_id, "canceled")

        # Clear in-memory pending payment
        if user_id_str:
            from coffee_oracle.services.payment_service import get_payment_service
            ps = get_payment_service()
            if ps:
                ps.clear_pending_payment(int(user_id_str))

            await self._notify_user(
                int(user_id_str),
                "❌ Платёж отменён.\n"
                "Если хотите оформить подписку, используйте /subscribe",
            )

        logger.info("Webhook: payment %s canceled", payment_id)
        return {"ok": True, "message": "Payment canceled"}

    async def _handle_refund_succeeded(self, refund: dict) -> dict:
        """Process a successful refund — log it."""
        refund_id = refund.get("id")
        payment_id = refund.get("payment_id")
        logger.info("Webhook: refund %s succeeded for payment %s", refund_id, payment_id)
        # Refund handling is typically manual; just log for now
        return {"ok": True, "message": "Refund noted"}

    async def _notify_user(self, telegram_id: int, text: str) -> None:
        """Send a notification to the user via Telegram."""
        try:
            await self.bot.send_message(chat_id=telegram_id, text=text)
        except Exception as e:
            logger.warning("Failed to notify user %d via webhook: %s", telegram_id, e)
