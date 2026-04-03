"""Управление конфигурацией приложения.

Загружает настройки из переменных окружения через python-dotenv.
Обязательные переменные проверяются при старте приложения.
BOT_TOKEN и MAX_BOT_TOKEN — опциональны по отдельности,
но хотя бы один из них должен быть задан.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Конфигурация приложения."""

    # Telegram-бот (опционально — если не задан, Telegram-бот не запускается)
    bot_token: Optional[str] = None

    # Админ-панель (обязательно)
    admin_username: str = ""
    admin_password: str = ""
    secret_key: str = "default-secret-key"

    # База данных
    database_url: str = ""
    admin_port: int = 8008

    # MAX-бот (опционально — если не задан, MAX-бот не запускается)
    max_bot_token: Optional[str] = None

    # LiteLLM / OpenAI конфигурация
    litellm_model: str = "openai/gpt-4.1"
    litellm_api_key: Optional[str] = None
    litellm_api_base: Optional[str] = None
    litellm_api_version: Optional[str] = None
    litellm_timeout: int = 30
    litellm_max_tokens: int = 1500
    litellm_temperature: float = 0.8

    @classmethod
    def from_env(cls) -> "Config":
        """Загрузка конфигурации из переменных окружения.

        Обязательные: ADMIN_USERNAME, ADMIN_PASSWORD,
        LITELLM_API_KEY (или OPENAI_API_KEY).
        Хотя бы один из: BOT_TOKEN, MAX_BOT_TOKEN.

        Raises:
            ValueError: Если обязательная переменная не задана
                       или не задан ни один токен бота.
        """
        # Токены ботов (оба опциональны по отдельности)
        bot_token = os.getenv("BOT_TOKEN", "").strip() or None
        max_bot_token = os.getenv("MAX_BOT_TOKEN", "").strip() or None

        # Хотя бы один бот должен быть настроен
        if not bot_token and not max_bot_token:
            raise ValueError(
                "Необходимо задать хотя бы одну переменную: "
                "BOT_TOKEN (Telegram) или MAX_BOT_TOKEN (MAX)"
            )

        # Админ-панель (обязательно)
        admin_username = os.getenv("ADMIN_USERNAME")
        admin_password = os.getenv("ADMIN_PASSWORD")
        secret_key = os.getenv("SECRET_KEY", "default-secret-key")
        db_name = os.getenv("DB_NAME", "coffee_oracle.db")

        if not admin_username:
            raise ValueError("ADMIN_USERNAME — обязательная переменная окружения")
        if not admin_password:
            raise ValueError("ADMIN_PASSWORD — обязательная переменная окружения")

        database_url = f"sqlite+aiosqlite:///data/{db_name}"

        # Опциональный порт админки
        admin_port = int(os.getenv("ADMIN_PORT", "8008"))

        # LiteLLM / OpenAI конфигурация
        litellm_model = os.getenv("LITELLM_MODEL", "gpt-4o-mini")
        litellm_api_key = os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        litellm_api_base = os.getenv("LITELLM_API_BASE")
        litellm_api_version = os.getenv("LITELLM_API_VERSION")
        litellm_timeout = int(os.getenv("LITELLM_TIMEOUT", "30"))
        litellm_max_tokens = int(os.getenv("LITELLM_MAX_TOKENS", "1500"))
        litellm_temperature = float(os.getenv("LITELLM_TEMPERATURE", "0.8"))

        if not litellm_api_key:
            raise ValueError(
                "LITELLM_API_KEY или OPENAI_API_KEY — обязательная переменная окружения"
            )

        return cls(
            bot_token=bot_token,
            admin_username=admin_username,
            admin_password=admin_password,
            secret_key=secret_key,
            database_url=database_url,
            admin_port=admin_port,
            max_bot_token=max_bot_token,
            litellm_model=litellm_model,
            litellm_api_key=litellm_api_key,
            litellm_api_base=litellm_api_base,
            litellm_api_version=litellm_api_version,
            litellm_timeout=litellm_timeout,
            litellm_max_tokens=litellm_max_tokens,
            litellm_temperature=litellm_temperature,
        )


# Глобальный экземпляр конфигурации
config = Config.from_env()
