"""Main bot class."""

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
    """Main Coffee Oracle Bot class."""
    
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
        """Set up bot commands menu."""
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
            logger.info("Bot commands menu set up successfully")
            
            # Verify commands were set
            current_commands = await self.bot.get_my_commands()
            logger.info(f"Current bot commands: {[cmd.command for cmd in current_commands]}")
            
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")
            # Continue anyway, commands are not critical for bot operation

    async def start_polling(self) -> None:
        """Start bot polling."""
        logger.info("Starting Coffee Oracle Bot...")
        
        try:
            # Set up bot commands
            await self.setup_bot_commands()
            
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Error in bot polling: {e}")
            raise
        finally:
            await self.bot.session.close()
    
    async def stop(self) -> None:
        """Stop bot."""
        logger.info("Stopping Coffee Oracle Bot...")
        await self.bot.session.close()