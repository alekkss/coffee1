"""Главный класс Telegram-бота."""

import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from coffee_oracle.bot.handlers import router
from coffee_oracle.bot.middleware import MediaGroupMiddleware
from coffee_oracle.config import config
from coffee_oracle.services.error_notifier import setup_error_notifier

logger = logging.getLogger(__name__)


class CoffeeOracleBot:
    """Главный класс Telegram-бота Coffee Oracle."""

    def __init__(self):
        self.bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher()

        # Register middleware
        self.dp.message.middleware(MediaGroupMiddleware())

        # Include routers
        self.dp.include_router(router)

    async def setup_bot_commands(self) -> None:
        """Установка меню команд бота."""
        commands = [
            BotCommand(command="start", description="🔮 Начать работу с ботом"),
            BotCommand(command="help", description="❓ Частые вопросы"),
            BotCommand(command="predict", description="🔮 Получить предсказание"),
            BotCommand(command="random", description="🎯 Случайное предсказание"),
            BotCommand(command="subscribe", description="💎 Подписка"),
            BotCommand(command="about", description="ℹ️ О боте"),
            BotCommand(command="support", description="📞 Поддержка"),
        ]

        try:
            await self.bot.set_my_commands(commands)
            logger.info("Меню команд бота установлено успешно")

            # Verify commands were set
            current_commands = await self.bot.get_my_commands()
            logger.info("Текущие команды бота: %s", [cmd.command for cmd in current_commands])

        except Exception as e:
            logger.error("Ошибка установки команд бота: %s", e)
            # Continue anyway, commands are not critical for bot operation

    async def start_polling(self) -> None:
        """Запуск polling бота."""
        logger.info("Запуск Coffee Oracle Bot...")

        try:
            # Set up error notifier (sends errors to Telegram)
            setup_error_notifier(self.bot)

            # Set up bot commands
            await self.setup_bot_commands()

            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error("Ошибка в polling бота: %s", e)
            raise
        finally:
            await self.bot.session.close()

    async def stop(self) -> None:
        """Остановка бота."""
        logger.info("Остановка Coffee Oracle Bot...")
        await self.bot.session.close()