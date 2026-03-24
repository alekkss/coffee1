#!/usr/bin/env python3
"""Direct OpenAI API test."""

import asyncio
import base64
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_openai_direct():
    """Test OpenAI API directly."""
    
    print("🧪 Testing OpenAI API directly...")
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("❌ OPENAI_API_KEY not found")
        return False
    
    print(f"✅ API Key found: {api_key[:20]}...")
    
    try:
        # Try to import and use OpenAI directly
        import openai
        from openai import AsyncOpenAI
        
        print("✅ OpenAI package imported successfully")
        
        # Create client
        client = AsyncOpenAI(api_key=api_key)
        print("✅ OpenAI client created")
        
        # Create a simple test image (100x100 pixel PNG with coffee cup pattern)
        import io
        from PIL import Image, ImageDraw
        
        # Create a simple coffee cup image
        img = Image.new('RGB', (100, 100), color='white')
        draw = ImageDraw.Draw(img)
        
        # Draw a simple coffee cup
        draw.ellipse([20, 20, 80, 80], fill='brown', outline='black')
        draw.ellipse([25, 25, 75, 75], fill='black')
        draw.rectangle([75, 40, 85, 60], fill='black')  # handle
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        test_image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        print("🔮 Sending test request to OpenAI...")
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Ты — мистический оракул. Дай короткое позитивное предсказание на русском языке."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Посмотри на эту картинку и дай позитивное предсказание:"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{test_image_b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=150,
            temperature=0.8
        )
        
        prediction = response.choices[0].message.content
        print(f"✅ OpenAI response received!")
        print(f"🔮 Prediction: {prediction}")
        
        await client.close()
        print("✅ Client closed successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ OpenAI test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_openai_direct())
    sys.exit(0 if success else 1)