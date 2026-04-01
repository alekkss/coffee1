"""Tests for soft delete functionality."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from coffee_oracle.database.models import Base, User, Prediction, Payment
from coffee_oracle.database.repositories import (
    UserRepository, PredictionRepository, SubscriptionRepository
)


@pytest_asyncio.fixture
async def test_db():
    """Create test database with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield async_session

    await engine.dispose()


@pytest_asyncio.fixture
async def session(test_db):
    """Get a test session."""
    async with test_db() as session:
        yield session


@pytest_asyncio.fixture
async def user_repo(session):
    return UserRepository(session)


@pytest_asyncio.fixture
async def prediction_repo(session):
    return PredictionRepository(session)


@pytest_asyncio.fixture
async def sub_repo(session):
    return SubscriptionRepository(session)


# --- Soft delete basic tests ---

@pytest.mark.asyncio
async def test_soft_delete_user(user_repo):
    """Soft-deleted user should not appear in normal queries."""
    user = await user_repo.create_user(telegram_id=100, username="alice", full_name="Alice")

    result = await user_repo.soft_delete_user(user.id)
    assert result is True

    # Should not be found by normal queries
    assert await user_repo.get_user_by_telegram_id(100) is None
    assert await user_repo.get_user_by_id(user.id) is None

    # Count should be 0
    assert await user_repo.get_users_count() == 0


@pytest.mark.asyncio
async def test_soft_delete_nonexistent_user(user_repo):
    """Soft deleting a non-existent user returns False."""
    result = await user_repo.soft_delete_user(9999)
    assert result is False


@pytest.mark.asyncio
async def test_soft_delete_already_deleted(user_repo):
    """Soft deleting an already deleted user returns False."""
    user = await user_repo.create_user(telegram_id=101, username="bob", full_name="Bob")
    await user_repo.soft_delete_user(user.id)

    result = await user_repo.soft_delete_user(user.id)
    assert result is False


# --- Restore tests ---

@pytest.mark.asyncio
async def test_restore_user(user_repo):
    """Restored user should appear in normal queries again."""
    user = await user_repo.create_user(telegram_id=200, username="carol", full_name="Carol")
    await user_repo.soft_delete_user(user.id)

    result = await user_repo.restore_user(user.id)
    assert result is True

    restored = await user_repo.get_user_by_telegram_id(200)
    assert restored is not None
    assert restored.id == user.id
    assert restored.deleted_at is None


@pytest.mark.asyncio
async def test_restore_active_user(user_repo):
    """Restoring an active (non-deleted) user returns False."""
    user = await user_repo.create_user(telegram_id=201, username="dave", full_name="Dave")

    result = await user_repo.restore_user(user.id)
    assert result is False


@pytest.mark.asyncio
async def test_restore_nonexistent_user(user_repo):
    """Restoring a non-existent user returns False."""
    result = await user_repo.restore_user(9999)
    assert result is False


# --- Data preservation tests ---

@pytest.mark.asyncio
async def test_predictions_preserved_after_soft_delete(session, user_repo, prediction_repo):
    """Predictions should remain in DB after user is soft-deleted."""
    user = await user_repo.create_user(telegram_id=300, username="eve", full_name="Eve")

    await prediction_repo.create_prediction(
        user_id=user.id,
        photo_file_id="photo1",
        prediction_text="Your future is bright"
    )
    await prediction_repo.create_prediction(
        user_id=user.id,
        photo_file_id="photo2",
        prediction_text="Good things are coming"
    )

    await user_repo.soft_delete_user(user.id)

    # Predictions should still exist
    count = await prediction_repo.get_user_predictions_count(user.id)
    assert count == 2

    predictions = await prediction_repo.get_user_predictions(user.id)
    assert len(predictions) == 2


@pytest.mark.asyncio
async def test_payments_preserved_after_soft_delete(session, user_repo, sub_repo):
    """Payments should remain in DB after user is soft-deleted."""
    user = await user_repo.create_user(telegram_id=301, username="frank", full_name="Frank")

    await sub_repo.create_payment(
        user_id=user.id, amount=30000, label="pay_001"
    )

    await user_repo.soft_delete_user(user.id)

    # Payment should still exist
    payments = await sub_repo.get_user_payments(user.id)
    assert len(payments) == 1
    assert payments[0].amount == 30000  # 300 rubles in kopecks


# --- Filtering tests ---

@pytest.mark.asyncio
async def test_get_all_users_excludes_deleted(user_repo):
    """get_all_users should exclude soft-deleted users by default."""
    await user_repo.create_user(telegram_id=400, username="active1", full_name="Active One")
    user2 = await user_repo.create_user(telegram_id=401, username="deleted1", full_name="Deleted One")
    await user_repo.create_user(telegram_id=402, username="active2", full_name="Active Two")

    await user_repo.soft_delete_user(user2.id)

    users = await user_repo.get_all_users()
    assert len(users) == 2
    assert all(u.deleted_at is None for u in users)


@pytest.mark.asyncio
async def test_get_all_users_include_deleted(user_repo):
    """get_all_users with include_deleted=True should return all users."""
    await user_repo.create_user(telegram_id=410, username="a1", full_name="A1")
    user2 = await user_repo.create_user(telegram_id=411, username="a2", full_name="A2")

    await user_repo.soft_delete_user(user2.id)

    users = await user_repo.get_all_users(include_deleted=True)
    assert len(users) == 2


@pytest.mark.asyncio
async def test_search_excludes_deleted(user_repo):
    """Search methods should exclude soft-deleted users."""
    user1 = await user_repo.create_user(telegram_id=500, username="searchme", full_name="Search Me")
    await user_repo.create_user(telegram_id=501, username="searchme2", full_name="Search Me Too")

    await user_repo.soft_delete_user(user1.id)

    by_username = await user_repo.search_users_by_username("searchme")
    assert len(by_username) == 1
    assert by_username[0].telegram_id == 501

    by_name = await user_repo.search_users_by_full_name("Search Me")
    assert len(by_name) == 1
    assert by_name[0].telegram_id == 501


@pytest.mark.asyncio
async def test_users_count_excludes_deleted(user_repo):
    """User count should exclude soft-deleted users."""
    await user_repo.create_user(telegram_id=600, username="u1", full_name="U1")
    user2 = await user_repo.create_user(telegram_id=601, username="u2", full_name="U2")
    await user_repo.create_user(telegram_id=602, username="u3", full_name="U3")

    await user_repo.soft_delete_user(user2.id)

    assert await user_repo.get_users_count() == 2


# --- Re-registration after soft delete ---

@pytest.mark.asyncio
async def test_create_user_restores_soft_deleted(user_repo):
    """Creating a user with same telegram_id as soft-deleted should restore them."""
    user = await user_repo.create_user(telegram_id=700, username="ghost", full_name="Ghost")
    original_id = user.id

    await user_repo.soft_delete_user(user.id)

    # Re-register with same telegram_id
    restored = await user_repo.create_user(
        telegram_id=700, username="ghost_new", full_name="Ghost Reborn"
    )

    assert restored.id == original_id
    assert restored.deleted_at is None
    assert restored.username == "ghost_new"
    assert restored.full_name == "Ghost Reborn"


# --- Subscription stats with soft delete ---

@pytest.mark.asyncio
async def test_subscription_stats_exclude_deleted(session, user_repo, sub_repo):
    """Subscription stats should not count soft-deleted users."""
    user1 = await user_repo.create_user(telegram_id=800, username="vip1", full_name="VIP1")
    user2 = await user_repo.create_user(telegram_id=801, username="vip2", full_name="VIP2")

    await sub_repo.set_vip_status(user1.telegram_id, "tester")
    await sub_repo.set_vip_status(user2.telegram_id, "partner")

    stats = await sub_repo.get_subscription_stats()
    assert stats["vip_users"] == 2

    await user_repo.soft_delete_user(user1.id)
    session.expire_all()

    stats = await sub_repo.get_subscription_stats()
    assert stats["vip_users"] == 1


@pytest.mark.asyncio
async def test_vip_list_excludes_deleted(session, user_repo, sub_repo):
    """VIP user list should exclude soft-deleted users."""
    user1 = await user_repo.create_user(telegram_id=900, username="v1", full_name="V1")
    user2 = await user_repo.create_user(telegram_id=901, username="v2", full_name="V2")

    await sub_repo.set_vip_status(user1.telegram_id, "tester")
    await sub_repo.set_vip_status(user2.telegram_id, "tester")

    await user_repo.soft_delete_user(user1.id)

    vips = await sub_repo.get_all_vip_users()
    assert len(vips) == 1
    assert vips[0].telegram_id == 901
