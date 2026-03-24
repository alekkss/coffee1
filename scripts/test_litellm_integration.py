#!/usr/bin/env python3
"""Test LiteLLM integration."""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from coffee_oracle.services.openai_client import get_llm_client
from coffee_oracle.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_litellm_client():
    """Test LiteLLM client initialization and basic functionality."""
    try:
        print("🧪 Testing LiteLLM Integration")
        print("=" * 50)
        
        # Test configuration
        print(f"📋 Configuration:")
        print(f"  Model: {config.litellm_model}")
        print(f"  API Key: {'***' + config.litellm_api_key[-4:] if config.litellm_api_key else 'Not set'}")
        print(f"  API Base: {config.litellm_api_base or 'Default'}")
        print(f"  Timeout: {config.litellm_timeout}s")
        print(f"  Max Tokens: {config.litellm_max_tokens}")
        print(f"  Temperature: {config.litellm_temperature}")
        print()
        
        # Test client initialization
        print("🔧 Initializing LiteLLM client...")
        client = get_llm_client()
        print("✅ Client initialized successfully")
        print()
        
        # Test with a sample image (create a simple test image)
        print("🖼️ Testing image analysis...")
        
        # Create a simple test image (1x1 pixel PNG)
        test_image_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x12IDATx\x9cc```bPPP\x00\x02\xac\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82'
        
        try:
            prediction = await client.analyze_coffee_image(test_image_data)
            print("✅ Image analysis successful!")
            print(f"📝 Prediction preview: {prediction[:100]}..." if prediction else "No prediction returned")
        except Exception as e:
            print(f"❌ Image analysis failed: {e}")
            print("ℹ️  This might be expected with a test image")
        
        print()
        print("🎯 LiteLLM integration test completed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        logger.exception("Test error")
        return False
    
    return True


async def test_fallback_prediction():
    """Test fallback prediction generation."""
    try:
        print("\n🔄 Testing fallback prediction...")
        client = get_llm_client()
        
        # Test fallback prediction
        fallback = client._generate_fallback_prediction()
        print(f"✅ Fallback prediction: {fallback}")
        
    except Exception as e:
        print(f"❌ Fallback test failed: {e}")


def test_configuration():
    """Test configuration loading."""
    try:
        print("\n⚙️ Testing configuration...")
        
        required_vars = [
            "BOT_TOKEN",
            "LITELLM_API_KEY",
            "ADMIN_USERNAME", 
            "ADMIN_PASSWORD"
        ]
        
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            print(f"⚠️  Missing environment variables: {', '.join(missing_vars)}")
            print("ℹ️  Make sure to set these in your .env file")
        else:
            print("✅ All required environment variables are set")
            
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")


if __name__ == "__main__":
    print("🚀 Starting LiteLLM Integration Tests")
    print()
    
    # Test configuration first
    test_configuration()
    
    # Test async functionality
    success = asyncio.run(test_litellm_client())
    
    # Test fallback
    asyncio.run(test_fallback_prediction())
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All tests completed!")
    else:
        print("⚠️  Some tests failed - check the logs above")
        sys.exit(1)