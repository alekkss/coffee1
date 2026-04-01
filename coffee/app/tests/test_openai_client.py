"""Test OpenAI client."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from coffee_oracle.services.openai_client import LLMClient
from coffee_oracle.utils.errors import OpenAIError


@pytest.fixture
def openai_client():
    """Create OpenAI client for testing."""
    with patch('coffee_oracle.services.openai_client.config') as mock_config:
        mock_config.litellm_api_key = "test_api_key"
        mock_config.litellm_api_base = "https://test.example.com"
        mock_config.litellm_timeout = 30
        mock_config.litellm_model = "test-model"
        return LLMClient()


@pytest.mark.asyncio
async def test_positive_content_validation(openai_client):
    """Test positive content validation."""
    # Test positive content
    assert not openai_client._contains_negative_content("Вас ждет успех и радость!")
    assert not openai_client._contains_negative_content("Любовь и счастье войдут в вашу жизнь")
    
    # Test negative content
    assert openai_client._contains_negative_content("Вас ждет болезнь")
    assert openai_client._contains_negative_content("Возможна неудача в делах")
    assert openai_client._contains_negative_content("Берегитесь потерь")


@pytest.mark.asyncio
async def test_fallback_prediction_generation(openai_client):
    """Test fallback prediction generation."""
    prediction = await openai_client._generate_fallback_prediction()
    
    assert isinstance(prediction, str)
    assert len(prediction) > 0
    assert "🔮" in prediction
    assert not openai_client._contains_negative_content(prediction)


@pytest.mark.asyncio
async def test_analyze_coffee_image_success(openai_client):
    """Test successful image analysis."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "🔮 Вас ждет успех и радость!"
    
    with patch.object(openai_client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        result = await openai_client.analyze_coffee_image(b"fake_image_data")
        
        assert result == "🔮 Вас ждет успех и радость!"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_coffee_image_rate_limit(openai_client):
    """Test rate limit handling."""
    import openai
    
    with patch.object(openai_client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = openai.RateLimitError("Rate limit exceeded", response=None, body=None)
        
        with pytest.raises(OpenAIError) as exc_info:
            await openai_client.analyze_coffee_image(b"fake_image_data")
        
        assert "слишком яркие" in str(exc_info.value)


@pytest.mark.asyncio
async def test_analyze_coffee_image_api_error(openai_client):
    """Test API error handling."""
    import openai
    
    with patch.object(openai_client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = openai.APIError("API error", response=None, body=None)
        
        with pytest.raises(OpenAIError) as exc_info:
            await openai_client.analyze_coffee_image(b"fake_image_data")
        
        assert "недоступны" in str(exc_info.value)


@pytest.mark.asyncio
async def test_analyze_coffee_image_negative_content_filtering(openai_client):
    """Test negative content filtering."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Вас ждет болезнь и неудача"
    
    with patch.object(openai_client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        with patch.object(openai_client, '_generate_fallback_prediction', new_callable=AsyncMock) as mock_fallback:
            mock_fallback.return_value = "🔮 Позитивное предсказание"
            
            result = await openai_client.analyze_coffee_image(b"fake_image_data")
            
            assert result == "🔮 Позитивное предсказание"
            mock_fallback.assert_called_once()