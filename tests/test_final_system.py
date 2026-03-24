#!/usr/bin/env python3
"""Final system test to verify all components are working."""

import asyncio
import base64
import json
import logging
from datetime import datetime

import aiohttp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "secret_pass"
BASE_URL = "http://localhost:8000"

def get_auth_header():
    """Get Basic Auth header."""
    credentials = f"{ADMIN_USERNAME}:{ADMIN_PASSWORD}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded_credentials}"}

async def test_endpoint(session, endpoint, description):
    """Test a single endpoint."""
    try:
        url = f"{BASE_URL}{endpoint}"
        headers = get_auth_header()
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(f"✅ {description}: OK")
                return True, data
            else:
                logger.error(f"❌ {description}: HTTP {response.status}")
                return False, None
    except Exception as e:
        logger.error(f"❌ {description}: {e}")
        return False, None

async def test_dashboard_page(session):
    """Test dashboard HTML page."""
    try:
        url = f"{BASE_URL}/"
        headers = get_auth_header()
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                html = await response.text()
                if "Coffee Oracle Admin Dashboard" in html:
                    logger.info("✅ Dashboard HTML page: OK")
                    return True
                else:
                    logger.error("❌ Dashboard HTML page: Missing title")
                    return False
            else:
                logger.error(f"❌ Dashboard HTML page: HTTP {response.status}")
                return False
    except Exception as e:
        logger.error(f"❌ Dashboard HTML page: {e}")
        return False

async def main():
    """Run all tests."""
    logger.info("🚀 Starting Coffee Oracle System Tests")
    logger.info("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        tests = [
            ("/health", "Health Check"),
            ("/api/dashboard", "Dashboard Stats"),
            ("/api/users", "Users API"),
            ("/api/predictions", "Predictions API"),
            ("/api/analytics?period=24h", "Analytics API (24h)"),
            ("/api/analytics?period=7d", "Analytics API (7d)"),
            ("/api/retention", "Retention Stats"),
        ]
        
        results = []
        
        # Test all API endpoints
        for endpoint, description in tests:
            success, data = await test_endpoint(session, endpoint, description)
            results.append(success)
            
            # Show sample data for key endpoints
            if success and data:
                if endpoint == "/api/dashboard":
                    kpi = data.get("kpi", {})
                    logger.info(f"   📊 Users: {kpi.get('total_users', 0)}, "
                              f"Predictions: {kpi.get('total_predictions', 0)}")
                elif endpoint == "/api/users":
                    logger.info(f"   👥 Found {len(data)} users")
                elif endpoint == "/api/predictions":
                    logger.info(f"   🔮 Found {len(data)} predictions")
        
        # Test dashboard HTML page
        dashboard_success = await test_dashboard_page(session)
        results.append(dashboard_success)
        
        # Summary
        logger.info("=" * 50)
        passed = sum(results)
        total = len(results)
        
        if passed == total:
            logger.info(f"🎉 ALL TESTS PASSED! ({passed}/{total})")
            logger.info("✨ Coffee Oracle System is fully operational!")
            logger.info("🌐 Admin Panel: http://localhost:8000")
            logger.info(f"🔐 Login: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
        else:
            logger.error(f"❌ SOME TESTS FAILED: {passed}/{total} passed")
            return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)