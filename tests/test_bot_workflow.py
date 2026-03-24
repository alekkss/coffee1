#!/usr/bin/env python3
"""Test bot workflow without Telegram."""

import asyncio
import base64
import io
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_bot_workflow():
    """Test complete bot workflow."""
    
    print("🧪 Testing Coffee Oracle Bot workflow...")
    
    # Set environment variables
    os.environ.update({
        'BOT_TOKEN': 'test_token',
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', 'test_key'),
        'ADMIN_USERNAME': 'admin',
        'ADMIN_PASSWORD': 'password',
        'DB_NAME': 'test_workflow.db'
    })
    
    try:
        # Test 1: Configuration
        print("\n1. Testing configuration...")
        from coffee_oracle.config import Config
        config = Config.from_env()
        print("✅ Configuration loaded")
        
        # Test 2: Database setup
        print("\n2. Testing database...")
        from coffee_oracle.database.connection import DatabaseManager
        from coffee_oracle.database.repositories import UserRepository, PredictionRepository
        
        db_manager = DatabaseManager(config.database_url)
        await db_manager.create_tables()
        print("✅ Database created")
        
        # Test 3: Create test user
        print("\n3. Testing user creation...")
        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.create_user(
                telegram_id=12345,
                username="testuser",
                full_name="Test User"
            )
            print(f"✅ User created: {user.full_name}")
            break
        
        # Test 4: OpenAI client
        print("\n4. Testing OpenAI client...")
        from coffee_oracle.services.openai_client import get_openai_client
        
        client = get_openai_client()
        print("✅ OpenAI client initialized")
        
        # Test 5: Generate test image
        print("\n5. Creating test coffee image...")
        from PIL import Image, ImageDraw
        
        img = Image.new('RGB', (200, 200), color='white')
        draw = ImageDraw.Draw(img)
        
        # Draw coffee cup with grounds
        draw.ellipse([50, 50, 150, 150], fill='brown', outline='black', width=3)
        draw.ellipse([60, 60, 140, 140], fill='#8B4513')  # coffee color
        draw.ellipse([70, 70, 130, 130], fill='#654321')  # darker coffee
        
        # Add some "grounds" patterns
        for i in range(10):
            x = 80 + (i % 3) * 15
            y = 80 + (i // 3) * 10
            draw.ellipse([x, y, x+5, y+5], fill='black')
        
        # Convert to bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        image_data = buffer.getvalue()
        
        print("✅ Test coffee image created")
        
        # Test 6: Analyze image
        print("\n6. Testing image analysis...")
        prediction = await client.analyze_coffee_image(image_data)
        print(f"✅ Prediction generated: {prediction[:100]}...")
        
        # Test 7: Save prediction
        print("\n7. Testing prediction storage...")
        async for session in db_manager.get_session():
            prediction_repo = PredictionRepository(session)
            saved_prediction = await prediction_repo.create_prediction(
                user_id=user.id,
                photo_file_id="test_file_id",
                prediction_text=prediction
            )
            print(f"✅ Prediction saved with ID: {saved_prediction.id}")
            break
        
        # Test 8: Retrieve user history
        print("\n8. Testing history retrieval...")
        async for session in db_manager.get_session():
            prediction_repo = PredictionRepository(session)
            history = await prediction_repo.get_user_predictions(user.id, limit=5)
            print(f"✅ Retrieved {len(history)} predictions from history")
            break
        
        # Test 9: Content validation
        print("\n9. Testing content validation...")
        positive_test = client._contains_negative_content("Вас ждет успех!")
        negative_test = client._contains_negative_content("Вас ждет болезнь")
        
        if not positive_test and negative_test:
            print("✅ Content validation works correctly")
        else:
            print("❌ Content validation failed")
            return False
        
        # Cleanup
        await db_manager.close()
        
        print("\n🎉 All workflow tests passed!")
        print(f"🔮 Sample prediction: {prediction}")
        
        return True
        
    except Exception as e:
        print(f"❌ Workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_bot_workflow())
    sys.exit(0 if success else 1)