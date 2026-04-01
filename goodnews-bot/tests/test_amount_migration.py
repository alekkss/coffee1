"""Tests for payment amount REAL→INTEGER (kopecks) migration."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from coffee_oracle.database.models import Base
from coffee_oracle.database.migrations import (
    check_payment_amount_to_integer,
    apply_payment_amount_to_integer,
)


@pytest_asyncio.fixture
async def migration_db():
    """Create test database with OLD schema (amount as REAL)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        # Create users table (needed for FK)
        await conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                full_name VARCHAR(255) NOT NULL,
                subscription_type VARCHAR(50) DEFAULT 'free',
                subscription_until DATETIME,
                vip_reason VARCHAR(255),
                recurring_payment_enabled INTEGER DEFAULT 0,
                telegram_recurring_payment_charge_id VARCHAR(255),
                deleted_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Create payments table with OLD schema (REAL amount)
        await conn.execute(text("""
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount REAL NOT NULL,
                label VARCHAR(100) UNIQUE NOT NULL,
                payment_id VARCHAR(100),
                status VARCHAR(50) DEFAULT 'pending' NOT NULL,
                is_recurring INTEGER DEFAULT 0 NOT NULL,
                telegram_recurring_payment_charge_id VARCHAR(255),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                completed_at DATETIME
            )
        """))

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield async_session
    await engine.dispose()


@pytest_asyncio.fixture
async def session(migration_db):
    async with migration_db() as session:
        yield session


@pytest.mark.asyncio
async def test_check_detects_real_column(session):
    """check_fn should return True when amount column is REAL."""
    result = await check_payment_amount_to_integer(session)
    assert result is True


@pytest.mark.asyncio
async def test_migration_converts_amounts(session):
    """Migration should convert rubles (REAL) to kopecks (INTEGER)."""
    # Insert test user
    await session.execute(text(
        "INSERT INTO users (id, telegram_id, full_name) VALUES (1, 100, 'Test')"
    ))
    # Insert payments with ruble amounts
    await session.execute(text(
        "INSERT INTO payments (user_id, amount, label, status) "
        "VALUES (1, 300.0, 'pay_1', 'completed')"
    ))
    await session.execute(text(
        "INSERT INTO payments (user_id, amount, label, status) "
        "VALUES (1, 199.99, 'pay_2', 'completed')"
    ))
    await session.execute(text(
        "INSERT INTO payments (user_id, amount, label, status) "
        "VALUES (1, 0.5, 'pay_3', 'pending')"
    ))
    await session.commit()

    # Apply migration
    await apply_payment_amount_to_integer(session)

    # Verify amounts are now in kopecks
    rows = await session.execute(text(
        "SELECT label, amount FROM payments ORDER BY label"
    ))
    payments = {r[0]: r[1] for r in rows.fetchall()}

    assert payments["pay_1"] == 30000   # 300.0 * 100
    assert payments["pay_2"] == 19999   # 199.99 * 100
    assert payments["pay_3"] == 50      # 0.5 * 100

    # Verify column type is now INTEGER
    col_info = await session.execute(text(
        "SELECT type FROM pragma_table_info('payments') WHERE name='amount'"
    ))
    assert col_info.fetchone()[0].upper() == "INTEGER"


@pytest.mark.asyncio
async def test_check_returns_false_after_migration(session):
    """check_fn should return False after migration is applied."""
    await session.execute(text(
        "INSERT INTO users (id, telegram_id, full_name) VALUES (1, 100, 'Test')"
    ))
    await session.commit()

    await apply_payment_amount_to_integer(session)

    result = await check_payment_amount_to_integer(session)
    assert result is False


@pytest.mark.asyncio
async def test_migration_preserves_all_columns(session):
    """Migration should preserve all payment data including recurring fields."""
    await session.execute(text(
        "INSERT INTO users (id, telegram_id, full_name) VALUES (1, 100, 'Test')"
    ))
    await session.execute(text(
        "INSERT INTO payments "
        "(user_id, amount, label, payment_id, status, is_recurring, "
        " telegram_recurring_payment_charge_id, completed_at) "
        "VALUES (1, 300.0, 'pay_rec', 'yk_123', 'completed', 1, 'tg_charge_abc', '2025-01-15 12:00:00')"
    ))
    await session.commit()

    await apply_payment_amount_to_integer(session)

    row = await session.execute(text("SELECT * FROM payments WHERE label='pay_rec'"))
    p = row.fetchone()

    assert p is not None
    # amount converted
    assert p[2] == 30000  # amount column index
    # other fields preserved
    assert p[4] == "yk_123"  # payment_id
    assert p[5] == "completed"  # status
    assert p[6] == 1  # is_recurring
    assert p[7] == "tg_charge_abc"  # telegram_recurring_payment_charge_id
