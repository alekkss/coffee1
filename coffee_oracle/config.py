"""Configuration management."""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration."""
    
    bot_token: str
    admin_username: str
    admin_password: str
    secret_key: str
    database_url: str
    admin_port: int = 8000
    
    # LiteLLM configuration
    litellm_model: str = "openai/gpt-4.1"
    litellm_api_key: Optional[str] = None
    litellm_api_base: Optional[str] = None
    litellm_api_version: Optional[str] = None
    litellm_timeout: int = 30
    litellm_max_tokens: int = 1500
    litellm_temperature: float = 0.8
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        bot_token = os.getenv("BOT_TOKEN")
        admin_username = os.getenv("ADMIN_USERNAME")
        admin_password = os.getenv("ADMIN_PASSWORD")
        secret_key = os.getenv("SECRET_KEY", "default-secret-key")
        db_name = os.getenv("DB_NAME", "coffee_oracle.db")
        
        if not bot_token:
            raise ValueError("BOT_TOKEN environment variable is required")
        if not admin_username:
            raise ValueError("ADMIN_USERNAME environment variable is required")
        if not admin_password:
            raise ValueError("ADMIN_PASSWORD environment variable is required")
            
        database_url = f"sqlite+aiosqlite:///data/{db_name}"
        
        # LiteLLM configuration
        litellm_model = os.getenv("LITELLM_MODEL", "gpt-4o-mini")
        litellm_api_key = os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        litellm_api_base = os.getenv("LITELLM_API_BASE")
        litellm_api_version = os.getenv("LITELLM_API_VERSION")
        litellm_timeout = int(os.getenv("LITELLM_TIMEOUT", "30"))
        litellm_max_tokens = int(os.getenv("LITELLM_MAX_TOKENS", "1500"))
        litellm_temperature = float(os.getenv("LITELLM_TEMPERATURE", "0.8"))
        
        if not litellm_api_key:
            raise ValueError("LITELLM_API_KEY or OPENAI_API_KEY environment variable is required")
        
        return cls(
            bot_token=bot_token,
            admin_username=admin_username,
            admin_password=admin_password,
            secret_key=secret_key,
            database_url=database_url,
            litellm_model=litellm_model,
            litellm_api_key=litellm_api_key,
            litellm_api_base=litellm_api_base,
            litellm_api_version=litellm_api_version,
            litellm_timeout=litellm_timeout,
            litellm_max_tokens=litellm_max_tokens,
            litellm_temperature=litellm_temperature,
        )


# Global config instance
config = Config.from_env()