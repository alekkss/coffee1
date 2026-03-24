"""Главный класс Telegram-бота.

Управляет жизненным циклом Telegram-бота: инициализация,
настройка команд, long polling. Устойчив к отсутствию
сети — не крашит приложение при недоступности Telegram API.
"""

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from coffee_oracle.bot.handlers import router
from coffee_oracle.bot.middleware import MediaGroupMiddleware
from coffee_oracle.config import config

logger = logging.getLogger(__name__)


class CoffeeOracleBot:
    """Telegram-бот Coffee Oracle."""

    def __init__(self) -> None:
        self._enabled = bool(config.bot_token and config.bot_token.strip())

        if not self._enabled:
            logger.info("BOT_TOKEN не задан — Telegram-бот не будет запущен")
            self.bot = None
            self.dp = None
            return

        self.bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()

        # Регистрация middleware
        self.dp.message.middleware(MediaGroupMiddleware())

        # Подключение роутеров
        self.dp.include_router(router)

    async def setup_bot_commands(self) -> None:
        """Настройка меню команд бота."""
        if not self._enabled or not self.bot:
            return

        commands = [
            BotCommand(command="start", description="🔮 Начать работу с ботом"),
            BotCommand(command="help", description="📚 Как гадать"),
            BotCommand(command="predict", description="🔮 Получить предсказание"),
            BotCommand(command="history", description="📜 Моя история"),
            BotCommand(command="random", description="🎯 Случайное предсказание"),
            BotCommand(command="about", description="ℹ️ О боте"),
            BotCommand(command="clear", description="🗑️ Очистить историю"),
            BotCommand(command="support", description="📞 Поддержка"),
        ]

        try:
            await self.bot.set_my_commands(commands)
            logger.info("Команды Telegram-бота настроены")

            current_commands = await self.bot.get_my_commands()
            logger.info(
                "Текущие команды: %s",
                [cmd.command for cmd in current_commands],
            )

        except Exception as e:
            logger.warning("Не удалось настроить команды Telegram-бота: %s", e)

    async def start_polling(self) -> None:
        """Запуск long polling Telegram-бота.

        Если Telegram API недоступен, логирует ошибку и повторяет
        попытки подключения с экспоненциальной задержкой вместо
        остановки всего приложения.
        """
        if not self._enabled or not self.bot or not self.dp:
            logger.info("Telegram-бот отключён — пропускаю запуск")
            # Бесконечный sleep чтобы задача не завершалась
            while True:
                await asyncio.sleep(3600)
            return

        logger.info("Запуск Telegram-бота...")

        retry_delay = 5.0
        max_retry_delay = 60.0

        while True:
            try:
                # Настройка команд (не критично при ошибке)
                await self.setup_bot_commands()

                # Запуск polling
                await self.dp.start_polling(self.bot)
                # Если polling завершился штатно — выходим
                break

            except asyncio.CancelledError:
                logger.info("Telegram-бот: polling отменён")
                break

            except Exception as e:
                logger.warning(
                    "Telegram-бот: ошибка подключения (повтор через %.0f сек): %s",
                    retry_delay, e,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def stop(self) -> None:
        """Остановка бота."""
        if not self._enabled or not self.bot:
            return

        logger.info("Остановка Telegram-бота...")
        try:
            await self.bot.session.close()
        except Exception as e:
            logger.warning("Ошибка при закрытии сессии Telegram: %s", e)
