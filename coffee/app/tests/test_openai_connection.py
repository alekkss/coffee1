#!/usr/bin/env python3
"""Test OpenAI connection."""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_openai_connection():
    """Test OpenAI API connection."""
    
    print("🧪 Testing OpenAI API connection...")
    
    # Set test environment variables
    os.environ.update({
        'BOT_TOKEN': 'test_token',
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', 'test_key'),
        'ADMIN_USERNAME': 'admin',
        'ADMIN_PASSWORD': 'password',
        'DB_NAME': 'test.db'
    })
    
    try:
        from coffee_oracle.services.openai_client import get_openai_client
        
        client = get_openai_client()
        print("✅ OpenAI client created successfully")
        
        # Test fallback prediction
        fallback = await client._generate_fallback_prediction()
        print(f"✅ Fallback prediction generated: {fallback[:50]}...")
        
        # Test content validation
        positive_test = client._contains_negative_content("Вас ждет успех и радость!")
        negative_test = client._contains_negative_content("Вас ждет болезнь")
        
        if not positive_test and negative_test:
            print("✅ Content validation works correctly")
        else:
            print("❌ Content validation failed")
            return False
        
        print("\n🎉 OpenAI client is ready for use!")
        return True
        
    except Exception as e:
        print(f"❌ OpenAI client test failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_openai_connection())
    sys.exit(0 if success else 1)