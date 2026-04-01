"""Database migrations manager."""

import logging
from typing import List, Callable, Awaitable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class Migration:
    """Single migration definition."""
    
    def __init__(self, name: str, check_fn: Callable[[AsyncSession], Awaitable[bool]], 
                 apply_fn: Callable[[AsyncSession], Awaitable[None]]):
        self.name = name
        self.check_fn = check_fn
        self.apply_fn = apply_fn


async def check_recurring_payments_migration(session: AsyncSession) -> bool:
    """Check if recurring payments migration is needed."""
    try:
        # Try to select the new columns
        await session.execute(text(
            "SELECT recurring_payment_enabled, telegram_recurring_payment_charge_id FROM users LIMIT 1"
        ))
        return False  # Migration not needed
    except Exception:
        return True  # Migration needed


async def apply_recurring_payments_migration(session: AsyncSession) -> None:
    """Apply recurring payments migration."""
    logger.info("Applying recurring payments migration...")
    
    # Add fields to users table
    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN recurring_payment_enabled INTEGER DEFAULT 0 NOT NULL"
        ))
        logger.info("Added recurring_payment_enabled to users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise
    
    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN telegram_recurring_payment_charge_id VARCHAR(255)"
        ))
        logger.info("Added telegram_recurring_payment_charge_id to users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise
    
    # Add fields to payments table
    try:
        await session.execute(text(
            "ALTER TABLE payments ADD COLUMN is_recurring INTEGER DEFAULT 0 NOT NULL"
        ))
        logger.info("Added is_recurring to payments")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise
    
    try:
        await session.execute(text(
            "ALTER TABLE payments ADD COLUMN telegram_recurring_payment_charge_id VARCHAR(255)"
        ))
        logger.info("Added telegram_recurring_payment_charge_id to payments")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise
    
    await session.commit()
    logger.info("✅ Recurring payments migration completed")


async def check_prediction_subscription_type_migration(session: AsyncSession) -> bool:
    """Check if prediction subscription_type migration is needed."""
    try:
        await session.execute(text(
            "SELECT subscription_type FROM predictions LIMIT 1"
        ))
        return False
    except Exception:
        return True


async def apply_prediction_subscription_type_migration(session: AsyncSession) -> None:
    """Apply prediction subscription_type migration."""
    logger.info("Applying prediction subscription_type migration...")

    try:
        await session.execute(text(
            "ALTER TABLE predictions ADD COLUMN subscription_type VARCHAR(50)"
        ))
        logger.info("Added subscription_type to predictions")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Prediction subscription_type migration completed")


async def check_payment_amount_to_integer(session: AsyncSession) -> bool:
    """Check if payment amount column needs to be converted from REAL to INTEGER (kopecks)."""
    try:
        result = await session.execute(text(
            "SELECT type FROM pragma_table_info('payments') WHERE name='amount'"
        ))
        row = result.fetchone()
        if row is None:
            return False  # No amount column or no payments table
        col_type = row[0].upper()
        # If it's still REAL/FLOAT, migration is needed
        return col_type in ("REAL", "FLOAT")
    except Exception:
        return False  # Table doesn't exist yet, nothing to migrate


async def apply_payment_amount_to_integer(session: AsyncSession) -> None:
    """Convert payments.amount from REAL (rubles) to INTEGER (kopecks).
    
    SQLite doesn't support ALTER COLUMN, so we recreate the table.
    """
    logger.info("Applying payment amount REAL→INTEGER migration...")

    # 1. Create new table with INTEGER amount
    await session.execute(text("""
        CREATE TABLE payments_new (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount INTEGER NOT NULL,
            label VARCHAR(100) UNIQUE NOT NULL,
            payment_id VARCHAR(100),
            status VARCHAR(50) DEFAULT 'pending' NOT NULL,
            is_recurring INTEGER DEFAULT 0 NOT NULL,
            telegram_recurring_payment_charge_id VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            completed_at DATETIME
        )
    """))

    # 2. Copy data, converting rubles to kopecks (multiply by 100)
    await session.execute(text("""
        INSERT INTO payments_new 
            (id, user_id, amount, label, payment_id, status, 
             is_recurring, telegram_recurring_payment_charge_id,
             created_at, completed_at)
        SELECT 
            id, user_id, CAST(ROUND(amount * 100) AS INTEGER), label, payment_id, status,
            is_recurring, telegram_recurring_payment_charge_id,
            created_at, completed_at
        FROM payments
    """))

    # 3. Drop old table and rename new one
    await session.execute(text("DROP TABLE payments"))
    await session.execute(text("ALTER TABLE payments_new RENAME TO payments"))

    await session.commit()
    logger.info("✅ Payment amount migration completed (REAL→INTEGER, rubles→kopecks)")


async def check_soft_delete_migration(session: AsyncSession) -> bool:
    """Check if soft delete migration is needed."""
    try:
        await session.execute(text("SELECT deleted_at FROM users LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_soft_delete_migration(session: AsyncSession) -> None:
    """Apply soft delete migration — add deleted_at to users."""
    logger.info("Applying soft delete migration...")

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN deleted_at DATETIME"
        ))
        logger.info("Added deleted_at to users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Soft delete migration completed")


async def check_user_email_migration(session: AsyncSession) -> bool:
    """Check if user email column migration is needed."""
    try:
        await session.execute(text("SELECT email FROM users LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_user_email_migration(session: AsyncSession) -> None:
    """Apply user email migration — add email to users."""
    logger.info("Applying user email migration...")

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN email VARCHAR(255)"
        ))
        logger.info("Added email to users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ User email migration completed")


# List of all migrations
MIGRATIONS: List[Migration] = [
    Migration(
        name="recurring_payments",
        check_fn=check_recurring_payments_migration,
        apply_fn=apply_recurring_payments_migration
    ),
    Migration(
        name="prediction_subscription_type",
        check_fn=check_prediction_subscription_type_migration,
        apply_fn=apply_prediction_subscription_type_migration
    ),
    Migration(
        name="soft_delete_users",
        check_fn=check_soft_delete_migration,
        apply_fn=apply_soft_delete_migration
    ),
    Migration(
        name="payment_amount_to_integer_kopecks",
        check_fn=check_payment_amount_to_integer,
        apply_fn=apply_payment_amount_to_integer
    ),
    Migration(
        name="user_email",
        check_fn=check_user_email_migration,
        apply_fn=apply_user_email_migration
    ),
]


async def run_migrations(session: AsyncSession) -> None:
    """Run all pending migrations."""
    logger.info("Checking for pending migrations...")
    
    migrations_applied = 0
    
    for migration in MIGRATIONS:
        try:
            needs_migration = await migration.check_fn(session)
            
            if needs_migration:
                logger.info(f"Applying migration: {migration.name}")
                await migration.apply_fn(session)
                migrations_applied += 1
            else:
                logger.debug(f"Migration {migration.name} already applied")
        except Exception as e:
            logger.error(f"Failed to apply migration {migration.name}: {e}")
            raise
    
    if migrations_applied > 0:
        logger.info(f"✅ Applied {migrations_applied} migration(s)")
    else:
        logger.info("✅ All migrations up to date")
