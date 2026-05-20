"""Тестовый скрипт: массовая отправка ремайндеров неактивным MAX-пользователям.

Находит всех пользователей MAX (source='max'), у которых последнее предсказание
(или регистрация, если предсказаний не было) было более 3 дней назад,
и отправляет им тестовое сообщение через MAX API.

Запуск:
    python scripts/send_max_inactive_reminders.py

Требования:
    - MAX_BOT_TOKEN задан в .env
    - База данных доступна (SQLite)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List

# Добавляем корень проекта в PYTHONPATH для импортов coffee_oracle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from coffee_oracle.bot import texts
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.max_bot.api_client import MaxApiClient
from coffee_oracle.max_bot.keyboards import MaxKeyboardManager

# ────────────────────────────────────────────
#  Настройка окружения
# ────────────────────────────────────────────

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────
#  Поиск неактивных пользователей
# ────────────────────────────────────────────

async def find_inactive_max_users(session: Any) -> List[Dict[str, Any]]:
    """Поиск MAX-пользователей без активности более 3 дней.

    Args:
        session: Асинхронная сессия SQLAlchemy.

    Returns:
        Список словарей с полями: id, telegram_id, username, full_name, last_activity.
    """
    cutoff = datetime.utcnow() - timedelta(days=3)

    query = text("""
        SELECT
            u.id,
            u.telegram_id,
            u.username,
            u.full_name,
            COALESCE(MAX(p.created_at), u.created_at) as last_activity
        FROM users u
        LEFT JOIN predictions p ON p.user_id = u.id
        WHERE u.source = 'max'
          AND u.deleted_at IS NULL
        GROUP BY u.id
        HAVING last_activity < :cutoff
        ORDER BY last_activity ASC
    """)

    result = await session.execute(query, {"cutoff": cutoff})
    rows = result.fetchall()

    users = []
    for row in rows:
        users.append({
            "id": row[0],
            "telegram_id": row[1],
            "username": row[2],
            "full_name": row[3],
            "last_activity": row[4],
        })

    return users


# ────────────────────────────────────────────
#  Отправка сообщений
# ────────────────────────────────────────────

async def send_test_reminder(
    api_client: MaxApiClient,
    max_user_id: int,
    full_name: str,
) -> bool:
    """Отправка тестового ремайндера пользователю MAX.

    Args:
        api_client: HTTP-клиент MAX API.
        max_user_id: ID пользователя на платформе MAX.
        full_name: Имя пользователя для персонализации.

    Returns:
        True если сообщение отправлено успешно, False иначе.
    """
    # Тестовый текст (можно заменить на texts.REMINDER_DAY_3)
    message_text = (
        f"☕ Привет, {full_name}!\n\n"
        "Твоя кофейная гуща скучает по тебе...\n\n"
        "Загляни в будущее — пришли фото, и я разгадаю знаки! 🔮\n\n"
        "(Это тестовое сообщение для неактивных пользователей)"
    )

    try:
        await api_client.send_message(
            user_id=max_user_id,
            text=message_text,
            attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
        )
        logger.info(
            "✅ Сообщение отправлено пользователю MAX %d (%s)",
            max_user_id, full_name,
        )
        return True
    except Exception as e:
        logger.error(
            "❌ Ошибка отправки пользователю MAX %d: %s",
            max_user_id, e,
        )
        return False


# ────────────────────────────────────────────
#  Главная логика
# ────────────────────────────────────────────

async def main() -> None:
    """Точка входа тестового скрипта."""
    logger.info("=" * 50)
    logger.info("Тестовый скрипт: ремайндеры неактивным MAX-пользователям")
    logger.info("=" * 50)

    # Проверка наличия MAX-токена
    if not config.max_bot_token:
        logger.error("MAX_BOT_TOKEN не задан в .env — отправка невозможна")
        sys.exit(1)

    # Инициализация клиента MAX API
    api_client = MaxApiClient(token=config.max_bot_token)

    # Инициализация БД (создаётся пул соединений)
    logger.info("Подключение к базе данных...")
    await db_manager.create_tables()

    # Поиск неактивных пользователей
    logger.info("Поиск MAX-пользователей без активности > 3 дней...")
    async for session in db_manager.get_session():
        inactive_users = await find_inactive_max_users(session)
        break

    if not inactive_users:
        logger.info("Неактивных пользователей не найдено. Выход.")
        return

    logger.info("Найдено %d неактивных пользователей", len(inactive_users))

    # Отправка сообщений
    sent_count = 0
    failed_count = 0

    for user in inactive_users:
        logger.info(
            "Пользователь %s (ID: %d, последняя активность: %s)",
            user["full_name"],
            user["telegram_id"],
            user["last_activity"],
        )

        success = await send_test_reminder(
            api_client=api_client,
            max_user_id=user["telegram_id"],
            full_name=user["full_name"],
        )

        if success:
            sent_count += 1
        else:
            failed_count += 1

        # Небольшая пауза, чтобы не спамить API
        await asyncio.sleep(0.5)

    # Закрытие ресурсов
    await api_client.close()
    await db_manager.close()

    # Итог
    logger.info("=" * 50)
    logger.info("Итоги рассылки:")
    logger.info("  Отправлено: %d", sent_count)
    logger.info("  Ошибок: %d", failed_count)
    logger.info("  Всего найдено: %d", len(inactive_users))
    logger.info("=" * 50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Скрипт прерван пользователем")
    except Exception as e:
        logger.error("Фатальная ошибка скрипта: %s", e)
        sys.exit(1)