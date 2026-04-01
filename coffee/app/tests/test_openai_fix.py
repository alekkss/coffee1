#!/usr/bin/env python3
"""Test OpenAI client with proper API key setup."""

import asyncio
import os
from coffee_oracle.services.openai_client import LLMClient


async def test_openai_connection():
    """Test OpenAI client initialization and basic functionality."""
    
    # Check if API key is set
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or api_key.startswith('$') or api_key == 'sk-proj-your-actual-openai-api-key-here':
        print("❌ OPENAI_API_KEY not properly set in .env file")
        print("Please set a real OpenAI API key in .env file:")
        print("OPENAI_API_KEY=sk-proj-your-actual-key-here")
        return False
    
    try:
        # Test client initialization
        print("🔧 Testing OpenAI client initialization...")
        client = OpenAIClient(api_key)
        print("✅ OpenAI client initialized successfully")
        
        # Test with a simple text message (no image)
        print("🔧 Testing basic OpenAI API call...")
        
        # Create a simple test image using PIL
        from PIL import Image
        import io
        
        # Create a simple 100x100 brown image (like coffee)
        img = Image.new('RGB', (100, 100), color=(101, 67, 33))  # Brown color
        
        # Add some random "coffee grounds" pattern
        import random
        pixels = img.load()
        for i in range(100):
            for j in range(100):
                if random.random() < 0.3:  # 30% chance for darker spots
                    pixels[i, j] = (50, 30, 15)  # Darker brown
        
        # Convert to bytes
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='JPEG')
        test_image_b64 = img_buffer.getvalue()
        
        prediction = await client.analyze_coffee_image(test_image_b64)
        
        if prediction:
            print("✅ OpenAI API call successful!")
            print(f"📝 Generated prediction: {prediction[:100]}...")
            return True
        else:
            print("❌ OpenAI API call returned empty result")
            return False
            
    except Exception as e:
        print(f"❌ OpenAI test failed: {e}")
        return False


if __name__ == "__main__":
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    success = asyncio.run(test_openai_connection())
    if success:
        print("\n🎉 OpenAI integration is working correctly!")
    else:
        print("\n💥 OpenAI integration needs fixing")