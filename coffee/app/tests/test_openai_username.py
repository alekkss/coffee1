"""Test OpenAI client with username injection."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from coffee_oracle.services.openai_client import LLMClient
from coffee_oracle.utils.errors import OpenAIError


@pytest.fixture
def openai_client():
    """Create OpenAI client for testing."""
    return LLMClient()


@pytest.mark.asyncio
async def test_analyze_coffee_image_with_username(openai_client):
    """Test image analysis with username."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "🔮 Привет, Иван! Вижу светлое будущее!"
    
    with patch.object(openai_client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        username = "Иван"
        result = await openai_client.analyze_coffee_image(
            b"fake_image_data", 
            username=username
        )
        
        assert result == "🔮 Привет, Иван! Вижу светлое будущее!"
        mock_create.assert_called_once()
        
        # Verify system prompt contains username
        call_args = mock_create.call_args
        messages = call_args.kwargs['messages']
        system_prompt = messages[0]['content']
        
        assert f"Имя пользователя: {username}" in system_prompt


@pytest.mark.asyncio
async def test_analyze_coffee_image_without_username(openai_client):
    """Test image analysis without username."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "🔮 Вижу светлое будущее!"
    
    with patch.object(openai_client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        result = await openai_client.analyze_coffee_image(b"fake_image_data")
        
        assert result == "🔮 Вижу светлое будущее!"
        mock_create.assert_called_once()
        
        # Verify system prompt does not contain username marker
        call_args = mock_create.call_args
        messages = call_args.kwargs['messages']
        system_prompt = messages[0]['content']
        
        assert "Имя пользователя:" not in system_prompt
