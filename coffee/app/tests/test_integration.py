#!/usr/bin/env python3
"""Simple integration test script."""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_basic_functionality():
    """Test basic functionality without external dependencies."""
    
    print("🧪 Testing Coffee Oracle Bot Integration...")
    
    # Test 1: Configuration loading
    print("\n1. Testing configuration...")
    try:
        # Set test environment variables
        os.environ.update({
            'BOT_TOKEN': 'test_token',
            'OPENAI_API_KEY': 'test_key',
            'ADMIN_USERNAME': 'admin',
            'ADMIN_PASSWORD': 'password',
            'DB_NAME': 'test.db'
        })
        
        from coffee_oracle.config import Config
        config = Config.from_env()
        
        assert config.bot_token == 'test_token'
        assert config.openai_api_key == 'test_key'
        assert 'test.db' in config.database_url
        print("✅ Configuration loading works")
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False
    
    # Test 2: Database models (skip if SQLAlchemy not available)
    print("\n2. Testing database models...")
    try:
        from coffee_oracle.database.models import User, Prediction
        print("✅ Database models import successfully")
        
    except ImportError as e:
        if "sqlalchemy" in str(e).lower():
            print("⚠️  Database models test skipped (SQLAlchemy not installed - will work in Docker)")
        else:
            print(f"❌ Database models test failed: {e}")
            return False
    except Exception as e:
        print(f"❌ Database models test failed: {e}")
        return False
    
    # Test 3: OpenAI client (without API calls)
    print("\n3. Testing OpenAI client...")
    try:
        from coffee_oracle.services.openai_client import OpenAIClient
        
        client = OpenAIClient("test_key")
        
        # Test content validation
        assert not client._contains_negative_content("Вас ждет успех!")
        assert client._contains_negative_content("Вас ждет болезнь")
        
        # Test fallback prediction
        fallback = await client._generate_fallback_prediction()
        assert isinstance(fallback, str)
        assert len(fallback) > 0
        assert "🔮" in fallback
        
        print("✅ OpenAI client basic functionality works")
        
    except ImportError as e:
        if "openai" in str(e).lower():
            print("⚠️  OpenAI client test skipped (OpenAI package not installed - will work in Docker)")
        else:
            print(f"❌ OpenAI client test failed: {e}")
            return False
    except Exception as e:
        print(f"❌ OpenAI client test failed: {e}")
        return False
    
    # Test 4: Error handling
    print("\n4. Testing error handling...")
    try:
        from coffee_oracle.utils.errors import CoffeeOracleError, format_error_message
        
        error = CoffeeOracleError("Test error", "Test details")
        formatted = format_error_message(error, user_friendly=True)
        assert formatted == "Test error"
        
        formatted_detailed = format_error_message(error, user_friendly=False)
        assert "Test details" in formatted_detailed
        
        print("✅ Error handling works")
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False
    
    # Test 5: Logging setup
    print("\n5. Testing logging...")
    try:
        from coffee_oracle.utils.logging import setup_logging, get_logger
        
        setup_logging(level="INFO")
        logger = get_logger("test")
        logger.info("Test log message")
        
        print("✅ Logging setup works")
        
    except Exception as e:
        print(f"❌ Logging test failed: {e}")
        return False
    
    print("\n🎉 All basic integration tests passed!")
    return True


async def test_docker_readiness():
    """Test Docker deployment readiness."""
    
    print("\n🐳 Testing Docker deployment readiness...")
    
    # Check required files
    required_files = [
        'Dockerfile',
        'docker-compose.yml',
        'requirements.txt',
        '.env.example',
        'main.py'
    ]
    
    for file_path in required_files:
        if not Path(file_path).exists():
            print(f"❌ Missing required file: {file_path}")
            return False
        print(f"✅ Found: {file_path}")
    
    # Check project structure
    required_dirs = [
        'coffee_oracle',
        'coffee_oracle/bot',
        'coffee_oracle/admin',
        'coffee_oracle/database',
        'coffee_oracle/services',
        'coffee_oracle/utils'
    ]
    
    for dir_path in required_dirs:
        if not Path(dir_path).exists():
            print(f"❌ Missing required directory: {dir_path}")
            return False
        print(f"✅ Found directory: {dir_path}")
    
    print("\n🎉 Docker deployment readiness check passed!")
    return True


async def main():
    """Run all integration tests."""
    
    print("=" * 60)
    print("Coffee Oracle Bot - Integration Test Suite")
    print("=" * 60)
    
    # Run basic functionality tests
    basic_success = await test_basic_functionality()
    
    # Run Docker readiness tests
    docker_success = await test_docker_readiness()
    
    # Final result
    print("\n" + "=" * 60)
    if basic_success and docker_success:
        print("🎉 ALL INTEGRATION TESTS PASSED!")
        print("\nThe Coffee Oracle Bot is ready for deployment!")
        print("\nNext steps:")
        print("1. Set up your .env file with real API keys")
        print("2. Run: docker compose up -d")
        print("3. Access admin panel at http://localhost:8000/admin")
        return 0
    else:
        print("❌ SOME TESTS FAILED!")
        print("\nPlease fix the issues before deployment.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)