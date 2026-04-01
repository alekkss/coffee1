"""Пакет MAX-бота для Coffee Oracle.

Содержит компоненты для работы с мессенджером MAX:
API-клиент, обработчики событий, обработчик фотографий,
клавиатуры и главный класс бота.
"""

from coffee_oracle.max_bot.api_client import MaxApiClient, MaxApiError
from coffee_oracle.max_bot.bot import MaxOracleBot
from coffee_oracle.max_bot.handlers import MaxBotHandlers
from coffee_oracle.max_bot.keyboards import MaxKeyboardManager
from coffee_oracle.max_bot.photo_processor import MaxPhotoProcessor

__all__ = [
    "MaxApiClient",
    "MaxApiError",
    "MaxOracleBot",
    "MaxBotHandlers",
    "MaxKeyboardManager",
    "MaxPhotoProcessor",
]
