"""Test configuration loading."""

import os
import pytest
from unittest.mock import patch

from coffee_oracle.config import Config
from coffee_oracle.utils.errors import ConfigurationError


def test_config_from_env_success():
    """Test successful configuration loading from environment."""
    with patch.dict(os.environ, {
        'BOT_TOKEN': 'test_bot_token',
        'OPENAI_API_KEY': 'test_openai_key',
        'ADMIN_USERNAME': 'test_admin',
        'ADMIN_PASSWORD': 'test_password',
        'DB_NAME': 'test.db'
    }):
        config = Config.from_env()
        
        assert config.bot_token == 'test_bot_token'
        assert config.openai_api_key == 'test_openai_key'
        assert config.admin_username == 'test_admin'
        assert config.admin_password == 'test_password'
        assert 'test.db' in config.database_url


def test_config_missing_bot_token():
    """Test configuration error when BOT_TOKEN is missing."""
    with patch.dict(os.environ, {
        'OPENAI_API_KEY': 'test_openai_key',
        'ADMIN_USERNAME': 'test_admin',
        'ADMIN_PASSWORD': 'test_password'
    }, clear=True):
        with pytest.raises(ValueError, match="BOT_TOKEN environment variable is required"):
            Config.from_env()


def test_config_missing_openai_key():
    """Test configuration error when OPENAI_API_KEY is missing."""
    with patch.dict(os.environ, {
        'BOT_TOKEN': 'test_bot_token',
        'ADMIN_USERNAME': 'test_admin',
        'ADMIN_PASSWORD': 'test_password'
    }, clear=True):
        with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
            Config.from_env()


def test_config_default_db_name():
    """Test default database name when DB_NAME is not provided."""
    with patch.dict(os.environ, {
        'BOT_TOKEN': 'test_bot_token',
        'OPENAI_API_KEY': 'test_openai_key',
        'ADMIN_USERNAME': 'test_admin',
        'ADMIN_PASSWORD': 'test_password'
    }):
        config = Config.from_env()
        assert 'coffee_oracle.db' in config.database_url