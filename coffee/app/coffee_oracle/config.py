"""Управление конфигурацией приложения.

Загружает настройки из переменных окружения через python-dotenv.
Все обязательные переменные проверяются при старте приложения.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Конфигурация приложения.

    Все параметры загружаются из переменных окружения
    через фабричный метод from_env().
    """

    # Telegram-бот (опционально — если не задан, Telegram-бот не запускается)
    bot_token: Optional[str] = None

    # Имя Telegram-бота (без @) для формирования реферальных ссылок
    bot_username: Optional[str] = None

    admin_username: str = ""
    admin_password: str = ""
    secret_key: str = "default-secret-key"
    database_url: str = ""
    domain: str = "localhost"
    admin_port: int = 8000

    # MAX-бот (опционально — если не задан, MAX-бот не запускается)
    max_bot_token: Optional[str] = None

    # Идентификатор MAX-бота для формирования реферальных ссылок
    # (часть URL вида "id9728167964_bot" из https://max.ru/id9728167964_bot)
    max_bot_id: Optional[str] = None

    # LiteLLM конфигурация
    litellm_model: str = "platto/gpt-5.1"
    litellm_model_fallback: Optional[str] = None
    litellm_api_key: Optional[str] = None
    litellm_api_base: Optional[str] = "https://api.1bitai.ru/v1"
    litellm_api_version: Optional[str] = None
    litellm_timeout: int = 30
    litellm_max_tokens: int = 1500
    litellm_temperature: float = 0.8

    # Telegram Payments конфигурация
    payment_provider_token: Optional[str] = None

    # Безопасность
    secure_cookies: bool = True

    # YooKassa direct API (для рекуррентных платежей)
    yookassa_shop_id: Optional[str] = None
    yookassa_secret_key: Optional[str] = None

    # Telegram ID администраторов для уведомлений об ошибках
    error_notify_telegram_ids: List[int] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Config":
        """Загрузка конфигурации из переменных окружения.

        Raises:
            ValueError: Если обязательные переменные не заданы
                        или не проходят валидацию.
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

        # Имя бота для реферальных ссылок (без @)
        bot_username = os.getenv("BOT_USERNAME", "").strip() or None

        # Идентификатор MAX-бота для реферальных ссылок
        # (например, "id9728167964_bot" из https://max.ru/id9728167964_bot)
        max_bot_id = os.getenv("MAX_BOT_ID", "").strip() or None

        admin_username = os.getenv("ADMIN_USERNAME")
        admin_password = os.getenv("ADMIN_PASSWORD")
        secret_key = os.getenv("SECRET_KEY")
        db_name = os.getenv("DB_NAME", "coffee_oracle.db")

        if not admin_username:
            raise ValueError("Переменная окружения ADMIN_USERNAME обязательна")
        if not admin_password:
            raise ValueError("Переменная окружения ADMIN_PASSWORD обязательна")
        if not secret_key or len(secret_key) < 32:
            raise ValueError(
                "Переменная окружения SECRET_KEY обязательна "
                "и должна содержать минимум 32 символа"
            )

        database_url = f"sqlite+aiosqlite:///data/{db_name}"
        domain = os.getenv("DOMAIN", "localhost")
        admin_port = int(os.getenv("ADMIN_PORT", "8000"))

        # LiteLLM конфигурация
        litellm_model = os.getenv("LITELLM_MODEL", "platto/gpt-5.1")
        litellm_model_fallback = os.getenv("LITELLM_MODEL_FALLBACK")
        litellm_api_key = os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        litellm_api_base = os.getenv("LITELLM_API_BASE")
        litellm_api_version = os.getenv("LITELLM_API_VERSION")
        litellm_timeout = int(os.getenv("LITELLM_TIMEOUT", "30"))
        litellm_max_tokens = int(os.getenv("LITELLM_MAX_TOKENS", "1500"))
        litellm_temperature = float(os.getenv("LITELLM_TEMPERATURE", "0.8"))

        if not litellm_api_key:
            raise ValueError(
                "Переменная окружения LITELLM_API_KEY или OPENAI_API_KEY обязательна"
            )

        # Telegram Payments конфигурация
        payment_provider_token = os.getenv("PAYMENT_PROVIDER_TOKEN")

        # Безопасность
        secure_cookies = os.getenv("SECURE_COOKIES", "true").lower() in ("true", "1", "yes")

        # YooKassa direct API (для рекуррентных платежей)
        yookassa_shop_id = os.getenv("YOOKASSA_SHOP_ID")
        yookassa_secret_key = os.getenv("YOOKASSA_SECRET_KEY")

        # ID администраторов для уведомлений об ошибках
        error_ids_raw = os.getenv("ERROR_NOTIFY_TELEGRAM_IDS", "").strip()
        error_notify_telegram_ids: List[int] = []
        if error_ids_raw:
            for part in error_ids_raw.split(","):
                part = part.strip()
                if part:
                    try:
                        error_notify_telegram_ids.append(int(part))
                    except ValueError:
                        pass

        return cls(
            bot_token=bot_token,
            bot_username=bot_username,
            admin_username=admin_username,
            admin_password=admin_password,
            secret_key=secret_key,
            database_url=database_url,
            domain=domain,
            admin_port=admin_port,
            max_bot_token=max_bot_token,
            max_bot_id=max_bot_id,
            litellm_model=litellm_model,
            litellm_model_fallback=litellm_model_fallback,
            litellm_api_key=litellm_api_key,
            litellm_api_base=litellm_api_base,
            litellm_api_version=litellm_api_version,
            litellm_timeout=litellm_timeout,
            litellm_max_tokens=litellm_max_tokens,
            litellm_temperature=litellm_temperature,
            payment_provider_token=payment_provider_token,
            secure_cookies=secure_cookies,
            yookassa_shop_id=yookassa_shop_id,
            yookassa_secret_key=yookassa_secret_key,
            error_notify_telegram_ids=error_notify_telegram_ids,
        )


# Глобальный экземпляр конфигурации
config = Config.from_env()
