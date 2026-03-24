#!/usr/bin/env python3
"""Test script to check if bot commands are working."""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from aiogram import Bot
from aiogram.types import BotCommand
from coffee_oracle.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_bot_commands():
    """Test bot commands setup."""
    bot = Bot(token=config.bot_token)
    
    try:
        # Get current commands
        current_commands = await bot.get_my_commands()
        logger.info("Current bot commands:")
        for cmd in current_commands:
            logger.info(f"  /{cmd.command} - {cmd.description}")
        
        if not current_commands:
            logger.warning("No commands found! Setting up commands...")
            
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
            
            await bot.set_my_commands(commands)
            logger.info("Commands set successfully!")
            
            # Verify
            new_commands = await bot.get_my_commands()
            logger.info("New commands:")
            for cmd in new_commands:
                logger.info(f"  /{cmd.command} - {cmd.description}")
        
        # Get bot info
        bot_info = await bot.get_me()
        logger.info(f"Bot info: @{bot_info.username} ({bot_info.first_name})")
        
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(test_bot_commands())