"""YooKassa payment service for subscription management.

Uses direct YooKassa API calls via httpx to avoid dependency conflicts.
"""

import asyncio
import base64
import logging
import uuid
from typing import Optional
import time

import httpx

from coffee_oracle.config import config

logger = logging.getLogger(__name__)

YOOKASSA_API_URL = "https://api.yookassa.ru/v3"


class PaymentService:
    """Service for handling YooKassa payments via direct API calls."""
    
    def __init__(self, shop_id: str, secret_key: str):
        """Initialize payment service with YooKassa credentials."""
        self.shop_id = shop_id
        self.secret_key = secret_key
        self._auth_header = self._create_auth_header()
        self._pending_payments: dict[int, str] = {}  # telegram_user_id -> payment_id
        logger.info("YooKassa PaymentService initialized for shop_id: %s", shop_id)
    
    def _create_auth_header(self) -> str:
        """Create Basic Auth header for YooKassa API."""
        credentials = f"{self.shop_id}:{self.secret_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
    
    def set_pending_payment(self, user_id: int, payment_id: str) -> None:
        """Store pending payment ID for a user."""
        self._pending_payments[user_id] = payment_id

    def get_pending_payment(self, user_id: int) -> Optional[str]:
        """Get pending payment ID for a user, or None if not found."""
        return self._pending_payments.get(user_id)

    def clear_pending_payment(self, user_id: int) -> None:
        """Remove pending payment ID for a user."""
        self._pending_payments.pop(user_id, None)

    def generate_payment_label(self, user_id: int) -> str:
        """Generate unique payment label for tracking."""
        return f"sub_{user_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    async def create_payment(
        self,
        amount: int,
        description: str,
        user_id: int,
        return_url: str = "https://t.me"
    ) -> dict:
        """
        Create a new payment via YooKassa API.
        
        Args:
            amount: Payment amount in kopecks
            description: Payment description
            user_id: Telegram user ID for metadata
            return_url: URL to redirect after payment
            
        Returns:
            dict with payment_id, confirmation_url, label, success
        """
        label = self.generate_payment_label(user_id)
        idempotency_key = str(uuid.uuid4())
        
        # Convert kopecks to rubles for YooKassa API
        amount_rubles = amount / 100
        
        payload = {
            "amount": {
                "value": f"{amount_rubles:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "description": description,
            "metadata": {
                "user_id": str(user_id),
                "label": label,
                "type": "subscription"
            }
        }
        
        headers = {
            "Authorization": self._auth_header,
            "Idempotence-Key": idempotency_key,
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{YOOKASSA_API_URL}/payments",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(
                        "Created YooKassa payment: id=%s, amount=%s, user_id=%s",
                        data["id"], amount, user_id
                    )
                    
                    return {
                        "success": True,
                        "payment_id": data["id"],
                        "confirmation_url": data["confirmation"]["confirmation_url"],
                        "label": label,
                        "status": data["status"]
                    }
                else:
                    error_msg = response.text
                    logger.error(
                        "YooKassa API error: status=%s, response=%s",
                        response.status_code, error_msg
                    )
                    return {
                        "success": False,
                        "error": f"API error: {response.status_code}"
                    }
                    
        except Exception as e:
            logger.error("Failed to create YooKassa payment: %s", e)
            return {
                "success": False,
                "error": str(e)
            }

    async def create_first_payment(
        self,
        amount: int,
        description: str,
        user_id: int,
        user_email: str = None,
        return_url: str = "https://t.me/oracul_coffee_bot",
    ) -> dict:
        """
        Create the first payment with save_payment_method for recurring billing.

        If the store doesn't support recurring payments (403 forbidden),
        automatically falls back to a one-time payment without
        ``save_payment_method``.

        Args:
            amount: Payment amount in kopecks.
            description: Payment description shown to the user.
            user_id: Telegram user ID.
            user_email: Customer e-mail for the 54-ФЗ receipt.
            return_url: URL the user is redirected to after payment.

        Returns:
            ``{success, payment_id, confirmation_url, label, recurring}``
            on success, ``{success: False, error}`` on failure.
            ``recurring`` is ``True`` when ``save_payment_method`` was accepted,
            ``False`` when the fallback one-time payment was used.
        """
        label = self.generate_payment_label(user_id)

        amount_rubles = amount / 100

        amount_block = {
            "value": f"{amount_rubles:.2f}",
            "currency": "RUB",
        }

        receipt_customer = {"email": user_email} if user_email else {}

        base_payload = {
            "amount": amount_block,
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "capture": True,
            "description": description,
            "metadata": {
                "user_id": str(user_id),
                "label": label,
                "type": "subscription",
            },
            "receipt": {
                "customer": receipt_customer,
                "items": [
                    {
                        "description": description,
                        "quantity": "1.00",
                        "amount": amount_block,
                        "vat_code": 1,
                        "payment_subject": "service",
                        "payment_mode": "full_payment",
                    }
                ],
            },
        }

        # Try recurring first, fallback to one-time on 403
        attempts = [
            (True, "recurring"),
            (False, "one-time fallback"),
        ]

        for save_method, attempt_label in attempts:
            payload = {**base_payload}
            if save_method:
                payload["save_payment_method"] = True

            idempotency_key = str(uuid.uuid4())
            headers = {
                "Authorization": self._auth_header,
                "Idempotence-Key": idempotency_key,
                "Content-Type": "application/json",
            }

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{YOOKASSA_API_URL}/payments",
                        json=payload,
                        headers=headers,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        logger.info(
                            "Created %s payment: id=%s, amount=%s, "
                            "user_id=%s, label=%s",
                            attempt_label,
                            data["id"],
                            amount,
                            user_id,
                            label,
                        )
                        return {
                            "success": True,
                            "payment_id": data["id"],
                            "confirmation_url": data[
                                "confirmation"
                            ]["confirmation_url"],
                            "label": label,
                            "recurring": save_method,
                        }

                    status_code = response.status_code
                    response_body = response.text

                    # 403 with save_payment_method → retry without it
                    if status_code == 403 and save_method:
                        logger.warning(
                            "Recurring payments not enabled for this store, "
                            "falling back to one-time payment"
                        )
                        continue

                    if 400 <= status_code < 500:
                        logger.error(
                            "YooKassa first-payment client error: "
                            "status=%s, response=%s",
                            status_code,
                            response_body,
                        )
                        return {
                            "success": False,
                            "error": f"API error: {status_code}",
                            "status_code": status_code,
                        }

                    # 5xx server errors
                    logger.error(
                        "YooKassa first-payment server error: "
                        "status=%s, response=%s",
                        status_code,
                        response_body,
                    )
                    return {
                        "success": False,
                        "error": f"Server error: {status_code}",
                        "status_code": status_code,
                    }

            except httpx.TimeoutException:
                logger.error(
                    "Timeout creating first payment for user %s",
                    user_id,
                )
                return {"success": False, "error": "Request timeout"}

            except Exception as e:
                logger.error(
                    "Failed to create first payment: %s", e,
                )
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "All payment attempts failed"}

    
    async def get_payment_status(self, payment_id: str) -> dict:
        """
        Get payment status from YooKassa.
        
        Args:
            payment_id: YooKassa payment ID
            
        Returns:
            dict with payment status info
        """
        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{YOOKASSA_API_URL}/payments/{payment_id}",
                    headers=headers
                )

                if response.status_code == 200:
                    data = response.json()
                    payment_method = data.get("payment_method", {})
                    return {
                        "success": True,
                        "payment_id": data["id"],
                        "status": data["status"],
                        "paid": data.get("paid", False),
                        "amount": data["amount"]["value"],
                        "currency": data["amount"]["currency"],
                        "metadata": data.get("metadata", {}),
                        "payment_method_saved": payment_method.get(
                            "saved", False
                        ),
                        "payment_method_id": payment_method.get(
                            "id", None
                        ),
                    }

                status_code = response.status_code
                response_body = response.text
                if 400 <= status_code < 500:
                    logger.error(
                        "YooKassa get-status client error: "
                        "status=%s, response=%s",
                        status_code,
                        response_body,
                    )
                    return {
                        "success": False,
                        "error": f"API error: {status_code}",
                        "status_code": status_code,
                    }

                # 5xx server errors
                logger.error(
                    "YooKassa get-status server error: "
                    "status=%s, response=%s",
                    status_code,
                    response_body,
                )
                return {
                    "success": False,
                    "error": f"Server error: {status_code}",
                    "status_code": status_code,
                }

        except httpx.TimeoutException:
            logger.error(
                "Timeout getting payment status for %s",
                payment_id,
            )
            return {
                "success": False,
                "error": "Request timeout",
            }

        except Exception as e:
            logger.error("Failed to get payment status: %s", e)
            return {
                "success": False,
                "error": str(e),
            }
    
    async def check_payment_completed(self, payment_id: str) -> bool:
        """
        Check if payment is completed (succeeded).

        Args:
            payment_id: YooKassa payment ID

        Returns:
            True if payment succeeded, False otherwise
        """
        result = await self.get_payment_status(payment_id)

        if result.get("success"):
            return result.get("status") == "succeeded" and result.get("paid") is True

        return False

    async def wait_for_payment_completion(
        self,
        payment_id: str,
        max_attempts: int = 4,
        initial_delay: float = 3.0,
        backoff_factor: float = 2.5,
    ) -> bool:
        """
        Poll payment status with exponential backoff until succeeded or attempts exhausted.

        Default schedule: 3s, 7.5s, 18.75s, 46.9s (~76s total wait).

        Args:
            payment_id: YooKassa payment ID
            max_attempts: Maximum number of status checks
            initial_delay: Seconds to wait before the first check
            backoff_factor: Multiplier applied to delay after each attempt

        Returns:
            True if payment succeeded within the retry window, False otherwise
        """
        delay = initial_delay

        for attempt in range(1, max_attempts + 1):
            await asyncio.sleep(delay)

            result = await self.get_payment_status(payment_id)

            if not result.get("success"):
                logger.warning(
                    "Payment %s status check #%d failed: %s",
                    payment_id, attempt, result.get("error"),
                )
            else:
                status = result.get("status")
                paid = result.get("paid", False)

                if status == "succeeded" and paid:
                    logger.info(
                        "Payment %s succeeded on attempt #%d", payment_id, attempt,
                    )
                    return True

                if status in ("canceled", "refunded"):
                    logger.info(
                        "Payment %s terminal status '%s' on attempt #%d",
                        payment_id, status, attempt,
                    )
                    return False

                logger.info(
                    "Payment %s still pending (status=%s, paid=%s), attempt #%d/%d",
                    payment_id, status, paid, attempt, max_attempts,
                )

            delay *= backoff_factor

        logger.warning(
            "Payment %s not completed after %d attempts", payment_id, max_attempts,
        )
        return False
    async def create_recurring_payment(
        self,
        amount: int,
        description: str,
        user_id: int,
        payment_method_id: str,
        user_email: str = None,
    ) -> dict:
        """
        Create a recurring payment using a saved payment method via YooKassa API.

        Args:
            amount: Payment amount in kopecks
            description: Payment description
            user_id: Telegram user ID for metadata
            payment_method_id: Saved payment method ID from previous payment
            user_email: Customer e-mail for the 54-ФЗ receipt (optional)

        Returns:
            dict with payment_id, success, status
        """
        label = self.generate_payment_label(user_id)
        idempotency_key = str(uuid.uuid4())
        amount_rubles = amount / 100

        amount_block = {
            "value": f"{amount_rubles:.2f}",
            "currency": "RUB",
        }

        receipt_customer = {"email": user_email} if user_email else {}

        payload = {
            "amount": amount_block,
            "capture": True,
            "payment_method_id": payment_method_id,
            "description": description,
            "metadata": {
                "user_id": str(user_id),
                "label": label,
                "type": "recurring_subscription"
            },
            "receipt": {
                "customer": receipt_customer,
                "items": [
                    {
                        "description": description,
                        "quantity": "1.00",
                        "amount": amount_block,
                        "vat_code": 1,
                        "payment_subject": "service",
                        "payment_mode": "full_payment",
                    }
                ],
            },
        }

        headers = {
            "Authorization": self._auth_header,
            "Idempotence-Key": idempotency_key,
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{YOOKASSA_API_URL}/payments",
                    json=payload,
                    headers=headers
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(
                        "Created recurring payment: "
                        "id=%s, amount=%s, user_id=%s",
                        data["id"], amount, user_id
                    )
                    return {
                        "success": True,
                        "payment_id": data["id"],
                        "label": label,
                        "status": data["status"]
                    }

                status_code = response.status_code
                response_body = response.text
                if 400 <= status_code < 500:
                    logger.error(
                        "YooKassa recurring payment client error: "
                        "status=%s, response=%s",
                        status_code,
                        response_body,
                    )
                    return {
                        "success": False,
                        "error": f"API error: {status_code}",
                        "status_code": status_code,
                    }

                # 5xx server errors
                logger.error(
                    "YooKassa recurring payment server error: "
                    "status=%s, response=%s",
                    status_code,
                    response_body,
                )
                return {
                    "success": False,
                    "error": f"Server error: {status_code}",
                    "status_code": status_code,
                }

        except httpx.TimeoutException:
            logger.error(
                "Timeout creating recurring payment for user %s",
                user_id,
            )
            return {
                "success": False,
                "error": "Request timeout",
            }

        except Exception as e:
            logger.error(
                "Failed to create recurring payment: %s", e
            )
            return {"success": False, "error": str(e)}



# Global payment service instance
_payment_service: Optional[PaymentService] = None


def get_payment_service() -> Optional[PaymentService]:
    """Get or create payment service instance."""
    global _payment_service

    if _payment_service is None:
        if config.yookassa_shop_id and config.yookassa_secret_key:
            _payment_service = PaymentService(
                shop_id=config.yookassa_shop_id,
                secret_key=config.yookassa_secret_key,
            )
            logger.info("PaymentService initialized with YooKassa")
        else:
            logger.warning("YooKassa credentials not configured")

    return _payment_service
