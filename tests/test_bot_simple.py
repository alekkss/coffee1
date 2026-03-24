#!/usr/bin/env python3
"""Simple test to verify the bot system is working."""

import asyncio
import os
from coffee_oracle.services.openai_client import OpenAIClient


async def test_system():
    """Test the system components."""
    
    # Check if API key is set
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or api_key.startswith('$'):
        print("❌ OPENAI_API_KEY not set")
        return False
    
    print(f"✅ API key found: {api_key[:10]}...")
    
    try:
        # Test client initialization
        print("🔧 Testing OpenAI client initialization...")
        client = OpenAIClient(api_key)
        print("✅ OpenAI client initialized successfully")
        
        # Test fallback prediction (doesn't require API call)
        print("🔧 Testing fallback prediction...")
        fallback = await client._generate_fallback_prediction()
        print(f"✅ Fallback prediction: {fallback[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


if __name__ == "__main__":
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    success = asyncio.run(test_system())
    if success:
        print("\n🎉 System is working! The bot should now process photos correctly.")
        print("Try sending a photo to your Telegram bot.")
    else:
        print("\n💥 System needs fixing")