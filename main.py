"""Главная точка входа приложения.

Запускает параллельно Telegram-бота, MAX-бота (опционально)
и админ-панель FastAPI. Управляет жизненным циклом всех сервисов.
"""

import asyncio
import signal
import sys
from typing import Any, Optional

import uvicorn

from coffee_oracle.admin.app import app as admin_app
from coffee_oracle.bot.bot import CoffeeOracleBot
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.utils.logging import setup_logging, get_logger

# Настройка логирования
setup_logging(level="INFO", log_file="logs/coffee_oracle.log")
logger = get_logger(__name__)


class ApplicationOrchestrator:
    """Главный оркестратор приложения.

    Управляет параллельным запуском и корректным завершением
    всех сервисов: Telegram-бот, MAX-бот, админ-панель.
    """

    def __init__(self) -> None:
        self.bot = CoffeeOracleBot()
        self.max_bot: Optional[Any] = None
        self.admin_server: Optional[uvicorn.Server] = None
        self.shutdown_event = asyncio.Event()

        # MAX-бот создаётся только если токен указан в конфигурации
        self._init_max_bot()

    def _init_max_bot(self) -> None:
        """Инициализация MAX-бота если токен доступен."""
        max_token = getattr(config, "max_bot_token", None)
        if not max_token:
            logger.info("MAX_BOT_TOKEN не задан — MAX-бот не будет запущен")
            return

        try:
            from coffee_oracle.max_bot.bot import MaxOracleBot

            self.max_bot = MaxOracleBot(token=max_token)
            logger.info("MAX-бот инициализирован")
        except ImportError as e:
            logger.warning(
                "Не удалось импортировать модуль MAX-бота: %s. "
                "MAX-бот не будет запущен",
                e,
            )
        except Exception as e:
            logger.error("Ошибка инициализации MAX-бота: %s", e)

    async def start_admin_server(self) -> None:
        """Запуск FastAPI админ-сервера."""
        config_uvicorn = uvicorn.Config(
            admin_app,
            host="0.0.0.0",
            port=config.admin_port,
            log_level="info",
            access_log=True,
        )

        self.admin_server = uvicorn.Server(config_uvicorn)
        logger.info("Запуск админ-сервера на порту %d", config.admin_port)

        try:
            await self.admin_server.serve()
        except Exception as e:
            logger.error("Ошибка админ-сервера: %s", e)
            raise

    async def start_bot(self) -> None:
        """Запуск Telegram-бота."""
        logger.info("Запуск Telegram-бота")

        try:
            await self.bot.start_polling()
        except Exception as e:
            logger.error("Ошибка Telegram-бота: %s", e)
            raise

    async def start_max_bot(self) -> None:
        """Запуск MAX-бота."""
        if not self.max_bot:
            return

        logger.info("Запуск MAX-бота")

        try:
            await self.max_bot.start_polling()
        except Exception as e:
            logger.error("Ошибка MAX-бота: %s", e)
            raise

    async def setup_database(self) -> None:
        """Инициализация базы данных."""
        logger.info("Настройка базы данных...")
        try:
            await db_manager.create_tables()
            logger.info("База данных настроена")
        except Exception as e:
            logger.error("Ошибка настройки базы данных: %s", e)
            raise

    async def start_services(self) -> None:
        """Запуск всех сервисов параллельно."""
        logger.info("Запуск сервисов Coffee Oracle...")

        # Сначала инициализация БД
        await self.setup_database()

        # Формирование списка задач
        tasks = [
            asyncio.create_task(self.start_bot(), name="telegram_bot"),
            asyncio.create_task(self.start_admin_server(), name="admin_server"),
        ]

        # MAX-бот добавляется только если инициализирован
        if self.max_bot:
            tasks.append(
                asyncio.create_task(self.start_max_bot(), name="max_bot")
            )
            logger.info("MAX-бот добавлен в список сервисов")

        try:
            # Ожидание сигнала завершения или завершения любой задачи
            _, pending = await asyncio.wait(
                tasks + [asyncio.create_task(self.shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Отмена оставшихся задач
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error("Ошибка сервиса: %s", e)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """Освобождение ресурсов при завершении."""
        logger.info("Освобождение ресурсов...")

        try:
            # Остановка Telegram-бота
            await self.bot.stop()

            # Остановка MAX-бота
            if self.max_bot:
                try:
                    await self.max_bot.stop()
                except Exception as e:
                    logger.error("Ошибка остановки MAX-бота: %s", e)

            # Остановка админ-сервера
            if self.admin_server:
                self.admin_server.should_exit = True

            # Закрытие соединений с БД
            await db_manager.close()

            logger.info("Ресурсы освобождены")
        except Exception as e:
            logger.error("Ошибка освобождения ресурсов: %s", e)

    def signal_handler(self, signum: int, _: Any) -> None:
        """Обработка сигналов завершения."""
        logger.info("Получен сигнал %d, начинаю завершение...", signum)
        self.shutdown_event.set()


async def main() -> None:
    """Главная асинхронная функция приложения."""
    orchestrator = ApplicationOrchestrator()

    # Установка обработчиков сигналов
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, orchestrator.signal_handler)

    try:
        await orchestrator.start_services()
    except KeyboardInterrupt:
        logger.info("Получено прерывание с клавиатуры")
    except Exception as e:
        logger.error("Ошибка приложения: %s", e)
        sys.exit(1)

    logger.info("Приложение Coffee Oracle остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение прервано пользователем")
    except Exception as e:
        logger.error("Критическая ошибка: %s", e)
        sys.exit(1)
