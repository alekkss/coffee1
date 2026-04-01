"""Subscription renewal scheduler.

Runs a background task that periodically checks for expiring subscriptions
and either auto-renews them via YooKassa API or notifies users.
"""

import asyncio
import logging
from typing import Optional

from aiogram import Bot

from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import SubscriptionRepository, SettingsRepository

logger = logging.getLogger(__name__)

# Check interval: every 6 hours
CHECK_INTERVAL_SECONDS = 6 * 60 * 60

# How many days before expiration to attempt renewal
RENEWAL_DAYS_BEFORE = 1


class SubscriptionScheduler:
    """Background scheduler for subscription renewals and notifications."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="subscription_scheduler")
        logger.info("Subscription scheduler started (interval: %ds)", CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Subscription scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        # Small initial delay to let the app fully start
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._check_expiring_subscriptions()
            except Exception as e:
                logger.error("Subscription scheduler error: %s", e, exc_info=True)

            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _check_expiring_subscriptions(self) -> None:
        """Find expiring subscriptions and process them."""
        logger.info("Checking for expiring subscriptions...")

        async for session in db_manager.get_session():
            sub_repo = SubscriptionRepository(session)
            settings_repo = SettingsRepository(session)

            # Get subscription price for renewal
            price_str = await settings_repo.get_setting("subscription_price")
            price = float(price_str) if price_str else 300.0

            # Find users whose premium expires within RENEWAL_DAYS_BEFORE days
            expiring_users = await sub_repo.get_expiring_premium_users(
                days=RENEWAL_DAYS_BEFORE
            )

            if not expiring_users:
                logger.info("No expiring subscriptions found")
                return

            logger.info("Found %d expiring subscriptions", len(expiring_users))

            for user in expiring_users:
                try:
                    await self._process_expiring_user(
                        sub_repo, user, price
                    )
                except Exception as e:
                    logger.error(
                        "Error processing expiring user %d: %s",
                        user.id, e, exc_info=True
                    )

    async def _process_expiring_user(
        self, sub_repo: SubscriptionRepository, user, price: float
    ) -> None:
        """Process a single expiring user: try auto-renew or notify."""
        recurring_enabled, charge_id = await sub_repo.is_recurring_enabled(user.id)

        if recurring_enabled and charge_id:
            # Attempt auto-renewal via YooKassa
            renewal_result = await self._attempt_auto_renewal(
                sub_repo, user, price, charge_id
            )
            if renewal_result == "success":
                await self._notify_user(
                    user.telegram_id,
                    "🔄 Подписка автоматически продлена!\n\n"
                    f"✅ Списано {price:.0f}₽ за следующий месяц.\n"
                    "Безлимитные предсказания продолжаются! ☕✨"
                )
                return
            elif renewal_result == "api_error":
                # Transient error — do NOT disable recurring, will retry next cycle
                logger.warning(
                    "Transient API error during auto-renewal for user %d; "
                    "will retry next cycle",
                    user.id,
                )
                return
            else:
                # payment_declined — disable recurring and notify user
                await sub_repo.disable_recurring_payment(user.id)
                await self._notify_user(
                    user.telegram_id,
                    "⚠️ Не удалось автоматически продлить подписку.\n\n"
                    "Возможно, карта заблокирована или недостаточно средств.\n"
                    "Автопродление отключено.\n\n"
                    "💳 Чтобы продлить подписку, используйте /subscribe"
                )
                return

        # No recurring — just notify about upcoming expiration
        if user.subscription_until:
            until_str = user.subscription_until.strftime("%d.%m.%Y")
        else:
            until_str = "скоро"

        await self._notify_user(
            user.telegram_id,
            f"⏰ Ваша подписка истекает {until_str}!\n\n"
            "Чтобы продолжить пользоваться безлимитными предсказаниями, "
            "продлите подписку.\n\n"
            "💎 Нажмите /subscribe для продления"
        )

    async def _attempt_auto_renewal(
        self,
        sub_repo: SubscriptionRepository,
        user,
        price: float,
        charge_id: str,
    ) -> str:
        """Attempt to auto-renew subscription via YooKassa saved payment method.

        Returns:
            "success" – payment succeeded, subscription extended.
            "api_error" – transient API error (5xx / timeout / network);
                          recurring should NOT be disabled.
            "payment_declined" – payment was declined or canceled;
                                 recurring should be disabled.
        """
        from coffee_oracle.services.payment_service import get_payment_service

        payment_service = get_payment_service()
        if not payment_service:
            logger.warning(
                "Cannot auto-renew for user %d: YooKassa not configured", user.id
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
                    "Auto-renewal payment failed for user %d: %s",
                    user.id, error_msg
                )
                # Transient API errors: 5xx, timeout, network issues
                if self._is_transient_api_error(result):
                    return "api_error"
                # 4xx or other non-transient errors → treat as decline
                return "payment_declined"

            payment_id = result["payment_id"]

            # Poll with exponential backoff
            completed = await payment_service.wait_for_payment_completion(payment_id)

            if completed:
                # Record payment and extend subscription
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
                logger.info("Auto-renewed subscription for user %d", user.id)
                return "success"
            else:
                logger.warning(
                    "Auto-renewal payment %s not completed for user %d",
                    payment_id, user.id
                )
                return "payment_declined"

        except Exception as e:
            logger.error("Auto-renewal error for user %d: %s", user.id, e)
            return "api_error"

    async def _notify_user(self, telegram_id: int, text: str) -> None:
        """Send notification to user via Telegram."""
        try:
            await self.bot.send_message(chat_id=telegram_id, text=text)
            logger.info("Sent subscription notification to user %d", telegram_id)
        except Exception as e:
            logger.warning(
                "Failed to notify user %d: %s", telegram_id, e
            )

    @staticmethod
    def _is_transient_api_error(result: dict) -> bool:
        """Check if a payment service error is transient (5xx / timeout / network).

        Transient errors should NOT cause recurring to be disabled — the
        scheduler will retry on the next cycle.
        """
        error = result.get("error", "")
        # 5xx server errors returned by PaymentService
        if error.startswith("Server error"):
            return True
        # Timeout errors
        if "timeout" in error.lower():
            return True
        # Status code in 5xx range
        status_code = result.get("status_code")
        if status_code is not None and status_code >= 500:
            return True
        # Network / connection errors (no status_code and not a known 4xx pattern)
        if status_code is None and not error.startswith("API error"):
            return True
        return False

