"""Test database operations."""

import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from coffee_oracle.database.models import Base, User, Payment, Prediction
from coffee_oracle.database.repositories import UserRepository, PredictionRepository, SubscriptionRepository


@pytest_asyncio.fixture
async def test_db():
    """Create test database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    yield async_session
    
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_creation(test_db):
    """Test user creation and retrieval."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        
        # Create user
        user = await user_repo.create_user(
            telegram_id=12345,
            username="testuser",
            full_name="Test User"
        )
        
        assert user.id is not None
        assert user.telegram_id == 12345
        assert user.username == "testuser"
        assert user.full_name == "Test User"
        assert isinstance(user.created_at, datetime)
        
        # Retrieve user
        retrieved_user = await user_repo.get_user_by_telegram_id(12345)
        assert retrieved_user is not None
        assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_user_uniqueness(test_db):
    """Test telegram_id uniqueness constraint."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        
        # Create first user
        user1 = await user_repo.create_user(
            telegram_id=12345,
            username="testuser1",
            full_name="Test User 1"
        )
        
        # Try to create user with same telegram_id
        user2 = await user_repo.create_user(
            telegram_id=12345,
            username="testuser2",
            full_name="Test User 2"
        )
        
        # Should return the existing user
        assert user1.id == user2.id
        assert user2.username == "testuser1"  # Original username preserved


@pytest.mark.asyncio
async def test_prediction_creation(test_db):
    """Test prediction creation and retrieval."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Create user first
        user = await user_repo.create_user(
            telegram_id=12345,
            username="testuser",
            full_name="Test User"
        )
        
        # Create prediction
        prediction = await prediction_repo.create_prediction(
            user_id=user.id,
            photo_file_id="test_file_id",
            prediction_text="Test prediction text"
        )
        
        assert prediction.id is not None
        assert prediction.user_id == user.id
        assert prediction.photo_file_id == "test_file_id"
        assert prediction.prediction_text == "Test prediction text"
        assert isinstance(prediction.created_at, datetime)


@pytest.mark.asyncio
async def test_user_predictions_limit(test_db):
    """Test user predictions retrieval with limit."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Create user
        user = await user_repo.create_user(
            telegram_id=12345,
            username="testuser",
            full_name="Test User"
        )
        
        # Create 7 predictions
        for i in range(7):
            await prediction_repo.create_prediction(
                user_id=user.id,
                photo_file_id=f"file_id_{i}",
                prediction_text=f"Prediction {i}"
            )
        
        # Get predictions with limit of 5
        predictions = await prediction_repo.get_user_predictions(user.id, limit=5)
        
        assert len(predictions) == 5
        # Should be ordered by creation date (newest first)
        assert predictions[0].prediction_text == "Prediction 6"
        assert predictions[4].prediction_text == "Prediction 2"


@pytest.mark.asyncio
async def test_user_search(test_db):
    """Test user search functionality."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        
        # Create test users
        await user_repo.create_user(12345, "alice", "Alice Smith")
        await user_repo.create_user(12346, "bob", "Bob Johnson")
        await user_repo.create_user(12347, "charlie", "Charlie Brown")
        
        # Search by username
        results = await user_repo.search_users_by_username("ali")
        assert len(results) == 1
        assert results[0].username == "alice"
        
        # Search by full name
        results = await user_repo.search_users_by_full_name("Johnson")
        assert len(results) == 1
        assert results[0].full_name == "Bob Johnson"


@pytest.mark.asyncio
async def test_update_payment_status_found(test_db):
    """Test updating payment status when payment exists."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)

        user = await user_repo.create_user(
            telegram_id=99999,
            username="payer",
            full_name="Test Payer"
        )

        payment = await sub_repo.create_payment(
            user_id=user.id,
            amount=30000,
            label="sub_99999_test",
            payment_id="yookassa_pay_123",
        )
        assert payment.status == "pending"

        result = await sub_repo.update_payment_status("yookassa_pay_123", "succeeded")
        assert result is True

        await session.refresh(payment)
        assert payment.status == "succeeded"
        assert payment.completed_at is not None


@pytest.mark.asyncio
async def test_update_payment_status_not_found(test_db):
    """Test updating payment status when payment does not exist."""
    async with test_db() as session:
        sub_repo = SubscriptionRepository(session)

        result = await sub_repo.update_payment_status("nonexistent_id", "succeeded")
        assert result is False


@pytest.mark.asyncio
async def test_update_payment_status_canceled(test_db):
    """Test updating payment status to canceled does not set completed_at."""
    async with test_db() as session:
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)

        user = await user_repo.create_user(
            telegram_id=88888,
            username="canceler",
            full_name="Test Canceler"
        )

        payment = await sub_repo.create_payment(
            user_id=user.id,
            amount=30000,
            label="sub_88888_test",
            payment_id="yookassa_pay_456",
        )

        result = await sub_repo.update_payment_status("yookassa_pay_456", "canceled")
        assert result is True

        await session.refresh(payment)
        assert payment.status == "canceled"
        assert payment.completed_at is None
