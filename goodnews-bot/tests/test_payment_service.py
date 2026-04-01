"""Unit tests for PaymentService.create_first_payment."""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from coffee_oracle.services.payment_service import PaymentService


@pytest.fixture
def payment_service():
    """Create a PaymentService instance with test credentials."""
    return PaymentService(shop_id="test_shop", secret_key="test_secret")


class TestCreateFirstPayment:
    """Tests for PaymentService.create_first_payment."""

    @pytest.mark.asyncio
    async def test_success_returns_payment_id_and_url(
        self, payment_service
    ):
        """Successful API response returns payment_id, confirmation_url, label."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_123",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/pay/123",
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            result = await payment_service.create_first_payment(
                amount=30000,
                description="Подписка Coffee Oracle (1 месяц)",
                user_id=123456,
                user_email="user@example.com",
            )

        assert result["success"] is True
        assert result["payment_id"] == "pay_123"
        assert result["confirmation_url"] == "https://yookassa.ru/pay/123"
        assert result["label"].startswith("sub_123456_")

    @pytest.mark.asyncio
    async def test_payload_contains_save_payment_method(
        self, payment_service
    ):
        """Payload must include save_payment_method: true."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_1",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/pay/1",
            },
        }

        captured_kwargs = {}

        async def capture_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = capture_post

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            await payment_service.create_first_payment(
                amount=30000,
                description="Test",
                user_id=1,
            )

        payload = captured_kwargs["json"]
        assert payload["save_payment_method"] is True
        assert payload["confirmation"]["type"] == "redirect"

    @pytest.mark.asyncio
    async def test_payload_contains_receipt_and_metadata(
        self, payment_service
    ):
        """Payload must include receipt (54-ФЗ) and metadata blocks."""
        captured_kwargs = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_2",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/pay/2",
            },
        }

        async def capture_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = capture_post

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            await payment_service.create_first_payment(
                amount=30000,
                description="Подписка",
                user_id=42,
                user_email="test@mail.ru",
            )

        payload = captured_kwargs["json"]

        # metadata
        assert payload["metadata"]["user_id"] == "42"
        assert payload["metadata"]["type"] == "subscription"
        assert "label" in payload["metadata"]

        # receipt
        assert "receipt" in payload
        assert payload["receipt"]["customer"]["email"] == "test@mail.ru"
        items = payload["receipt"]["items"]
        assert len(items) == 1
        assert items[0]["vat_code"] == 1
        assert items[0]["quantity"] == "1.00"
        assert items[0]["amount"]["value"] == "300.00"

    @pytest.mark.asyncio
    async def test_idempotence_key_is_unique(self, payment_service):
        """Each call must use a unique Idempotence-Key header."""
        keys = []

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_x",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/pay/x",
            },
        }

        async def capture_post(url, **kwargs):
            keys.append(kwargs["headers"]["Idempotence-Key"])
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = capture_post

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            await payment_service.create_first_payment(
                amount=30000, description="T", user_id=1,
            )
            await payment_service.create_first_payment(
                amount=30000, description="T", user_id=1,
            )

        assert len(keys) == 2
        assert keys[0] != keys[1]

    @pytest.mark.asyncio
    async def test_api_error_returns_failure(self, payment_service):
        """Non-200 response returns {success: False, error: ...}."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"type":"error","code":"invalid_request"}'

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            result = await payment_service.create_first_payment(
                amount=30000,
                description="Test",
                user_id=1,
            )

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self, payment_service):
        """Network exception returns {success: False, error: ...}."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            result = await payment_service.create_first_payment(
                amount=30000,
                description="Test",
                user_id=1,
            )

        assert result["success"] is False
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_amount_conversion_kopecks_to_rubles(
        self, payment_service
    ):
        """Amount in kopecks is correctly converted to rubles string."""
        captured_kwargs = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_a",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/pay/a",
            },
        }

        async def capture_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = capture_post

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            await payment_service.create_first_payment(
                amount=30000,
                description="Test",
                user_id=1,
            )

        payload = captured_kwargs["json"]
        assert payload["amount"]["value"] == "300.00"
        assert payload["amount"]["currency"] == "RUB"


class TestPendingPayments:
    """Tests for in-memory pending payment storage."""

    def test_set_and_get_pending_payment(self, payment_service):
        """set_pending_payment stores value retrievable by get_pending_payment."""
        payment_service.set_pending_payment(123, "pay_abc")
        assert payment_service.get_pending_payment(123) == "pay_abc"

    def test_get_pending_payment_returns_none_for_unknown_user(self, payment_service):
        """get_pending_payment returns None when no payment stored for user."""
        assert payment_service.get_pending_payment(999) is None

    def test_clear_pending_payment_removes_entry(self, payment_service):
        """clear_pending_payment removes the stored payment_id."""
        payment_service.set_pending_payment(123, "pay_abc")
        payment_service.clear_pending_payment(123)
        assert payment_service.get_pending_payment(123) is None

    def test_clear_pending_payment_noop_for_unknown_user(self, payment_service):
        """clear_pending_payment does not raise for unknown user."""
        payment_service.clear_pending_payment(999)  # should not raise

    def test_set_pending_payment_overwrites_previous(self, payment_service):
        """Setting a new payment_id for the same user overwrites the old one."""
        payment_service.set_pending_payment(123, "pay_old")
        payment_service.set_pending_payment(123, "pay_new")
        assert payment_service.get_pending_payment(123) == "pay_new"


class TestGetPaymentStatus:
    """Tests for PaymentService.get_payment_status with payment_method fields."""

    @pytest.mark.asyncio
    async def test_returns_payment_method_saved_and_id(self, payment_service):
        """Successful response includes payment_method_saved and payment_method_id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_abc",
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "300.00", "currency": "RUB"},
            "metadata": {"user_id": "123"},
            "payment_method": {
                "type": "bank_card",
                "id": "pm_xyz",
                "saved": True,
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            result = await payment_service.get_payment_status("pay_abc")

        assert result["success"] is True
        assert result["payment_method_saved"] is True
        assert result["payment_method_id"] == "pm_xyz"

    @pytest.mark.asyncio
    async def test_defaults_when_payment_method_missing(self, payment_service):
        """When API response has no payment_method, defaults are False/None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_no_pm",
            "status": "pending",
            "paid": False,
            "amount": {"value": "300.00", "currency": "RUB"},
            "metadata": {},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            result = await payment_service.get_payment_status("pay_no_pm")

        assert result["success"] is True
        assert result["payment_method_saved"] is False
        assert result["payment_method_id"] is None

    @pytest.mark.asyncio
    async def test_payment_method_saved_false(self, payment_service):
        """When payment_method.saved is false, payment_method_saved is False."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_unsaved",
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "300.00", "currency": "RUB"},
            "metadata": {},
            "payment_method": {
                "type": "bank_card",
                "id": "pm_unsaved",
                "saved": False,
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("coffee_oracle.services.payment_service.httpx.AsyncClient", return_value=mock_client):
            result = await payment_service.get_payment_status("pay_unsaved")

        assert result["success"] is True
        assert result["payment_method_saved"] is False
        assert result["payment_method_id"] == "pm_unsaved"


