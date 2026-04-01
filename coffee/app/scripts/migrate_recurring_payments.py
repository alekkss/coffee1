#!/usr/bin/env python3
"""Migration script to add recurring payment fields to database."""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.migrations import run_migrations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    """Run all pending migrations."""
    logger.info("Starting migration process...")
    
    async for session in db_manager.get_session():
        try:
            await run_migrations(session)
            logger.info("✅ Migration process completed!")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise
        break  # Only need one session


if __name__ == "__main__":
    asyncio.run(migrate())
