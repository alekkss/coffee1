"""Точка входа приложения Coffee Oracle.

Оркестрирует запуск всех компонентов: Telegram-бот, MAX-бот,
админ-панель (FastAPI), планировщик подписок. Компоненты
запускаются условно в зависимости от наличия токенов.
"""

import asyncio
import signal
import sys
from typing import Any, Optional

import uvicorn

from coffee_oracle.admin.app import app as admin_app
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.services.subscription_scheduler import SubscriptionScheduler
from coffee_oracle.utils.logging import setup_logging, get_logger

# Настройка логирования
setup_logging(level="INFO", log_file="logs/coffee_oracle.log")
logger = get_logger(__name__)


class ApplicationOrchestrator:
    """Главный оркестратор приложения.

    Управляет жизненным циклом всех компонентов:
    Telegram-бот (опционально), MAX-бот (опционально),
    админ-панель, планировщик подписок.
    Запускает их параллельно и обеспечивает корректное завершение.
    """

    def __init__(self):
        self.telegram_bot = None
        self.max_bot = None
        self.admin_server = None
        self.scheduler = None
        self.shutdown_event = asyncio.Event()

        # Инициализация Telegram-бота (если токен задан)
        if config.bot_token:
            from coffee_oracle.bot.bot import CoffeeOracleBot
            self.telegram_bot = CoffeeOracleBot()
            logger.info("Telegram-бот: инициализирован")
        else:
            logger.info("Telegram-бот: токен не задан, пропускаем")

        # Инициализация MAX-бота (если токен задан)
        if config.max_bot_token:
            from coffee_oracle.max_bot.bot import MaxOracleBot
            self.max_bot = MaxOracleBot(token=config.max_bot_token)
            logger.info("MAX-бот: инициализирован")
        else:
            logger.info("MAX-бот: токен не задан, пропускаем")

    async def start_admin_server(self) -> None:
        """Запуск FastAPI-сервера админ-панели."""
        config_uvicorn = uvicorn.Config(
            admin_app,
            host="0.0.0.0",
            port=config.admin_port,
            log_level="info",
            access_log=True,
        )

        self.admin_server = uvicorn.Server(config_uvicorn)
        logger.info("Админ-панель: запуск на порту %d", config.admin_port)

        try:
            await self.admin_server.serve()
        except Exception as e:
            logger.error("Админ-панель: ошибка — %s", e)
            raise

    async def start_telegram_bot(self) -> None:
        """Запуск Telegram-бота."""
        if not self.telegram_bot:
            return

        logger.info("Telegram-бот: запуск polling")

        try:
            await self.telegram_bot.start_polling()
        except Exception as e:
            logger.error("Telegram-бот: ошибка — %s", e)
            raise

    async def start_max_bot(self) -> None:
        """Запуск MAX-бота."""
        if not self.max_bot:
            return

        logger.info("MAX-бот: запуск polling")

        try:
            await self.max_bot.start_polling()
        except Exception as e:
            logger.error("MAX-бот: ошибка — %s", e)
            raise

    async def setup_database(self) -> None:
        """Инициализация базы данных и выполнение миграций."""
        logger.info("База данных: инициализация...")
        try:
            await db_manager.create_tables()
            logger.info("База данных: таблицы созданы")

            # Выполнение миграций
            logger.info("База данных: выполнение миграций...")
            from coffee_oracle.database.migrations import run_migrations
            async for session in db_manager.get_session():
                await run_migrations(session)
                break  # Достаточно одной сессии

            # Синхронизация суперадмина
            from coffee_oracle.admin.auth import ensure_superadmin
            await ensure_superadmin()
            logger.info("База данных: суперадмин синхронизирован")

        except Exception as e:
            logger.error("База данных: ошибка инициализации — %s", e)
            raise

    async def start_services(self) -> None:
        """Запуск всех сервисов параллельно."""
        logger.info("Coffee Oracle: запуск сервисов...")

        # Сначала инициализируем базу данных
        await self.setup_database()

        # Формируем список задач в зависимости от конфигурации
        tasks = []

        # Telegram-бот
        if self.telegram_bot:
            tasks.append(
                asyncio.create_task(
                    self.start_telegram_bot(), name="telegram_bot",
                )
            )

        # MAX-бот
        if self.max_bot:
            tasks.append(
                asyncio.create_task(
                    self.start_max_bot(), name="max_bot",
                )
            )

        # Админ-панель (запускается всегда)
        tasks.append(
            asyncio.create_task(
                self.start_admin_server(), name="admin_server",
            )
        )

        # Инициализация webhook-обработчика YooKassa
        # Работает при наличии хотя бы одного бота — определяет платформу
        # пользователя по полю source и шлёт уведомление в правильный мессенджер
        if self.telegram_bot or self.max_bot:
            from coffee_oracle.admin.app import init_webhook_handler
            init_webhook_handler(
                bot=self.telegram_bot.bot if self.telegram_bot else None,
                max_api_client=self.max_bot.api_client if self.max_bot else None,
            )

        # Запуск планировщика подписок
        # Работает при наличии хотя бы одного бота — отправляет уведомления
        # через Telegram и/или MAX в зависимости от платформы пользователя
        if self.telegram_bot or self.max_bot:
            self.scheduler = SubscriptionScheduler(
                bot=self.telegram_bot.bot if self.telegram_bot else None,
                max_api_client=self.max_bot.api_client if self.max_bot else None,
            )
            await self.scheduler.start()

        # Логируем итоговый состав запущенных компонентов
        component_names = [t.get_name() for t in tasks]
        logger.info(
            "Coffee Oracle: запущено %d компонентов: %s",
            len(component_names),
            ", ".join(component_names),
        )

        try:
            # Ожидаем сигнала завершения или падения любой задачи
            _, pending = await asyncio.wait(
                tasks + [asyncio.create_task(self.shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Отменяем оставшиеся задачи
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error("Coffee Oracle: ошибка сервисов — %s", e)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """Освобождение ресурсов при завершении."""
        logger.info("Coffee Oracle: освобождение ресурсов...")

        try:
            # Остановка Telegram-бота
            if self.telegram_bot:
                await self.telegram_bot.stop()

            # Остановка MAX-бота
            if self.max_bot:
                await self.max_bot.stop()

            # Остановка планировщика
            if self.scheduler:
                await self.scheduler.stop()

            # Остановка админ-сервера
            if self.admin_server:
                self.admin_server.should_exit = True

            # Закрытие соединений с БД
            await db_manager.close()

            logger.info("Coffee Oracle: ресурсы освобождены")
        except Exception as e:
            logger.error("Coffee Oracle: ошибка при освобождении ресурсов — %s", e)

    def signal_handler(self, signum: int, _: Any) -> None:
        """Обработка сигналов завершения (SIGTERM, SIGINT)."""
        logger.info("Получен сигнал %d, инициируем завершение...", signum)
        self.shutdown_event.set()


async def main() -> None:
    """Главная функция приложения."""
    orchestrator = ApplicationOrchestrator()

    # Настройка обработчиков сигналов
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, orchestrator.signal_handler)

    try:
        await orchestrator.start_services()
    except KeyboardInterrupt:
        logger.info("Получено прерывание с клавиатуры")
    except Exception as e:
        logger.error("Критическая ошибка приложения: %s", e)
        sys.exit(1)

    logger.info("Coffee Oracle: приложение остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение прервано пользователем")
    except Exception as e:
        logger.error("Фатальная ошибка: %s", e)
        sys.exit(1)
