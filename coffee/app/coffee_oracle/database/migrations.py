"""Менеджер миграций базы данных.

Содержит определения миграций и логику их применения
при каждом запуске приложения.
"""

import logging
from typing import List, Callable, Awaitable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class Migration:
    """Определение одной миграции."""

    def __init__(
        self,
        name: str,
        check_fn: Callable[[AsyncSession], Awaitable[bool]],
        apply_fn: Callable[[AsyncSession], Awaitable[None]],
    ):
        self.name = name
        self.check_fn = check_fn
        self.apply_fn = apply_fn


async def check_recurring_payments_migration(session: AsyncSession) -> bool:
    """Проверка необходимости миграции рекуррентных платежей."""
    try:
        await session.execute(text(
            "SELECT recurring_payment_enabled, telegram_recurring_payment_charge_id FROM users LIMIT 1"
        ))
        return False
    except Exception:
        return True


async def apply_recurring_payments_migration(session: AsyncSession) -> None:
    """Применение миграции рекуррентных платежей."""
    logger.info("Применение миграции рекуррентных платежей...")

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN recurring_payment_enabled INTEGER DEFAULT 0 NOT NULL"
        ))
        logger.info("Добавлено recurring_payment_enabled в users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN telegram_recurring_payment_charge_id VARCHAR(255)"
        ))
        logger.info("Добавлено telegram_recurring_payment_charge_id в users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    try:
        await session.execute(text(
            "ALTER TABLE payments ADD COLUMN is_recurring INTEGER DEFAULT 0 NOT NULL"
        ))
        logger.info("Добавлено is_recurring в payments")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    try:
        await session.execute(text(
            "ALTER TABLE payments ADD COLUMN telegram_recurring_payment_charge_id VARCHAR(255)"
        ))
        logger.info("Добавлено telegram_recurring_payment_charge_id в payments")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Миграция рекуррентных платежей завершена")


async def check_prediction_subscription_type_migration(session: AsyncSession) -> bool:
    """Проверка необходимости миграции subscription_type в predictions."""
    try:
        await session.execute(text(
            "SELECT subscription_type FROM predictions LIMIT 1"
        ))
        return False
    except Exception:
        return True


async def apply_prediction_subscription_type_migration(session: AsyncSession) -> None:
    """Применение миграции subscription_type в predictions."""
    logger.info("Применение миграции subscription_type в predictions...")

    try:
        await session.execute(text(
            "ALTER TABLE predictions ADD COLUMN subscription_type VARCHAR(50)"
        ))
        logger.info("Добавлено subscription_type в predictions")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Миграция subscription_type в predictions завершена")


async def check_payment_amount_to_integer(session: AsyncSession) -> bool:
    """Проверка необходимости конвертации amount из REAL в INTEGER (копейки)."""
    try:
        result = await session.execute(text(
            "SELECT type FROM pragma_table_info('payments') WHERE name='amount'"
        ))
        row = result.fetchone()
        if row is None:
            return False
        col_type = row[0].upper()
        return col_type in ("REAL", "FLOAT")
    except Exception:
        return False


async def apply_payment_amount_to_integer(session: AsyncSession) -> None:
    """Конвертация payments.amount из REAL (рубли) в INTEGER (копейки).

    SQLite не поддерживает ALTER COLUMN, поэтому пересоздаём таблицу.
    """
    logger.info("Применение миграции amount REAL→INTEGER...")

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

    await session.execute(text("DROP TABLE payments"))
    await session.execute(text("ALTER TABLE payments_new RENAME TO payments"))

    await session.commit()
    logger.info("✅ Миграция amount завершена (REAL→INTEGER, рубли→копейки)")


async def check_soft_delete_migration(session: AsyncSession) -> bool:
    """Проверка необходимости миграции мягкого удаления."""
    try:
        await session.execute(text("SELECT deleted_at FROM users LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_soft_delete_migration(session: AsyncSession) -> None:
    """Применение миграции мягкого удаления — добавление deleted_at в users."""
    logger.info("Применение миграции мягкого удаления...")

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN deleted_at DATETIME"
        ))
        logger.info("Добавлено deleted_at в users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Миграция мягкого удаления завершена")


async def check_user_email_migration(session: AsyncSession) -> bool:
    """Проверка необходимости миграции email пользователя."""
    try:
        await session.execute(text("SELECT email FROM users LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_user_email_migration(session: AsyncSession) -> None:
    """Применение миграции email — добавление email в users."""
    logger.info("Применение миграции email пользователя...")

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN email VARCHAR(255)"
        ))
        logger.info("Добавлено email в users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Миграция email пользователя завершена")


# ────────────────────────────────────────────
#  Миграция: добавление поля source в users
# ────────────────────────────────────────────


async def check_user_source_migration(session: AsyncSession) -> bool:
    """Проверка необходимости миграции поля source в users.

    Миграция нужна, если колонка source ещё не существует.
    """
    try:
        await session.execute(text("SELECT source FROM users LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_user_source_migration(session: AsyncSession) -> None:
    """Применение миграции source — добавление поля платформы-источника в users.

    Шаги:
    1. Добавляем колонку source со значением по умолчанию 'tg'
       (все существующие пользователи — из Telegram).
    2. Удаляем старый unique index на telegram_id (если существует).
    3. Создаём новый составной unique index на (telegram_id, source),
       чтобы один и тот же числовой ID из разных платформ не конфликтовал.
    """
    logger.info("Применение миграции source в users...")

    # Шаг 1: Добавляем колонку source
    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN source VARCHAR(10) DEFAULT 'tg' NOT NULL"
        ))
        logger.info("Добавлена колонка source в users (по умолчанию 'tg')")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    # Шаг 2: Удаляем старый unique index на telegram_id (если существует)
    # SQLite создаёт автоматические индексы для UNIQUE колонок.
    # Находим имя индекса и удаляем его.
    try:
        result = await session.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='users' AND sql LIKE '%telegram_id%' "
            "AND sql NOT LIKE '%source%'"
        ))
        old_indexes = result.fetchall()

        for row in old_indexes:
            index_name = row[0]
            if index_name:
                try:
                    await session.execute(text(f"DROP INDEX IF EXISTS \"{index_name}\""))
                    logger.info("Удалён старый индекс: %s", index_name)
                except Exception as drop_err:
                    logger.warning(
                        "Не удалось удалить индекс %s: %s (продолжаем)",
                        index_name, drop_err,
                    )
    except Exception as e:
        logger.warning("Ошибка при поиске старых индексов: %s (продолжаем)", e)

    # Шаг 3: Создаём составной unique index
    try:
        await session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_id_source "
            "ON users (telegram_id, source)"
        ))
        logger.info("Создан составной unique index: uq_users_telegram_id_source")
    except Exception as e:
        # Если индекс уже существует — это нормально
        if "already exists" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Миграция source в users завершена")


# ────────────────────────────────────────────
#  Миграция: создание таблицы partners
# ────────────────────────────────────────────


async def check_partners_table_migration(session: AsyncSession) -> bool:
    """Проверка необходимости создания таблицы partners.

    Миграция нужна, если таблица partners ещё не существует.
    """
    try:
        await session.execute(text("SELECT id FROM partners LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_partners_table_migration(session: AsyncSession) -> None:
    """Создание таблицы partners для реферальной системы.

    Таблица хранит данные партнёров: привязку к admin_users,
    уникальный реферальный код и описание.
    """
    logger.info("Применение миграции: создание таблицы partners...")

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY,
            admin_user_id INTEGER NOT NULL UNIQUE
                REFERENCES admin_users(id) ON DELETE CASCADE,
            referral_code VARCHAR(50) NOT NULL UNIQUE,
            description VARCHAR(500),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """))

    # Индекс для быстрого поиска по реферальному коду
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_partners_referral_code "
        "ON partners (referral_code)"
    ))

    await session.commit()
    logger.info("✅ Таблица partners создана")


# ────────────────────────────────────────────
#  Миграция: создание таблицы referral_clicks
# ────────────────────────────────────────────


async def check_referral_clicks_table_migration(session: AsyncSession) -> bool:
    """Проверка необходимости создания таблицы referral_clicks.

    Миграция нужна, если таблица referral_clicks ещё не существует.
    """
    try:
        await session.execute(text("SELECT id FROM referral_clicks LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_referral_clicks_table_migration(session: AsyncSession) -> None:
    """Создание таблицы referral_clicks для учёта переходов по реферальным ссылкам.

    Каждая запись — один переход пользователя по ссылке партнёра.
    """
    logger.info("Применение миграции: создание таблицы referral_clicks...")

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS referral_clicks (
            id INTEGER PRIMARY KEY,
            partner_id INTEGER NOT NULL
                REFERENCES partners(id) ON DELETE CASCADE,
            telegram_id BIGINT NOT NULL,
            source VARCHAR(10) NOT NULL DEFAULT 'tg',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """))

    # Индекс для быстрого подсчёта кликов по партнёру
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_referral_clicks_partner_id "
        "ON referral_clicks (partner_id)"
    ))

    # Индекс для поиска по telegram_id (дедупликация, аналитика)
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_referral_clicks_telegram_id "
        "ON referral_clicks (telegram_id)"
    ))

    await session.commit()
    logger.info("✅ Таблица referral_clicks создана")


# ────────────────────────────────────────────────────────
#  Миграция: добавление referred_by_partner_id в users
# ────────────────────────────────────────────────────────


async def check_user_referred_by_partner_migration(session: AsyncSession) -> bool:
    """Проверка необходимости добавления поля referred_by_partner_id в users.

    Миграция нужна, если колонка ещё не существует.
    """
    try:
        await session.execute(text(
            "SELECT referred_by_partner_id FROM users LIMIT 1"
        ))
        return False
    except Exception:
        return True


async def apply_user_referred_by_partner_migration(session: AsyncSession) -> None:
    """Добавление поля referred_by_partner_id в users.

    Хранит ID партнёра, по чьей ссылке пришёл пользователь.
    FK с ON DELETE SET NULL — при удалении партнёра поле обнуляется.
    """
    logger.info("Применение миграции: добавление referred_by_partner_id в users...")

    try:
        await session.execute(text(
            "ALTER TABLE users ADD COLUMN referred_by_partner_id INTEGER "
            "REFERENCES partners(id) ON DELETE SET NULL"
        ))
        logger.info("Добавлено referred_by_partner_id в users")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise

    await session.commit()
    logger.info("✅ Миграция referred_by_partner_id в users завершена")


# Список всех миграций (порядок важен!)
MIGRATIONS: List[Migration] = [
    Migration(
        name="recurring_payments",
        check_fn=check_recurring_payments_migration,
        apply_fn=apply_recurring_payments_migration,
    ),
    Migration(
        name="prediction_subscription_type",
        check_fn=check_prediction_subscription_type_migration,
        apply_fn=apply_prediction_subscription_type_migration,
    ),
    Migration(
        name="soft_delete_users",
        check_fn=check_soft_delete_migration,
        apply_fn=apply_soft_delete_migration,
    ),
    Migration(
        name="payment_amount_to_integer_kopecks",
        check_fn=check_payment_amount_to_integer,
        apply_fn=apply_payment_amount_to_integer,
    ),
    Migration(
        name="user_email",
        check_fn=check_user_email_migration,
        apply_fn=apply_user_email_migration,
    ),
    Migration(
        name="user_source",
        check_fn=check_user_source_migration,
        apply_fn=apply_user_source_migration,
    ),
    # --- Партнёрская система ---
    # Порядок важен: сначала partners, затем referral_clicks (FK на partners),
    # затем referred_by_partner_id в users (FK на partners).
    Migration(
        name="partners_table",
        check_fn=check_partners_table_migration,
        apply_fn=apply_partners_table_migration,
    ),
    Migration(
        name="referral_clicks_table",
        check_fn=check_referral_clicks_table_migration,
        apply_fn=apply_referral_clicks_table_migration,
    ),
    Migration(
        name="user_referred_by_partner",
        check_fn=check_user_referred_by_partner_migration,
        apply_fn=apply_user_referred_by_partner_migration,
    ),
]


async def run_migrations(session: AsyncSession) -> None:
    """Запуск всех ожидающих миграций."""
    logger.info("Проверка ожидающих миграций...")

    migrations_applied = 0

    for migration in MIGRATIONS:
        try:
            needs_migration = await migration.check_fn(session)

            if needs_migration:
                logger.info("Применение миграции: %s", migration.name)
                await migration.apply_fn(session)
                migrations_applied += 1
            else:
                logger.debug("Миграция %s уже применена", migration.name)
        except Exception as e:
            logger.error("Ошибка применения миграции %s: %s", migration.name, e)
            raise

    if migrations_applied > 0:
        logger.info("✅ Применено %d миграций", migrations_applied)
    else:
        logger.info("✅ Все миграции актуальны")
