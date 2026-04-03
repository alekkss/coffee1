"""Database connection management."""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coffee_oracle.config import config
from coffee_oracle.database.models import Base, PredictionPhoto


class DatabaseManager:
    """Database connection manager."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        
        # Enable WAL mode for SQLite
        from sqlalchemy import event
        
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self.async_session = async_sessionmaker(
            self.engine, 
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def create_tables(self) -> None:
        """Create all database tables."""
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        await self.check_and_migrate_db()

    async def check_and_migrate_db(self) -> None:
        """Check and migrate database schema."""
        async with self.engine.connect() as conn:
            # Check if columns exist in predictions table
            from sqlalchemy import text
            
            # Check photo_path column
            try:
                await conn.execute(text("SELECT photo_path FROM predictions LIMIT 1"))
            except Exception:
                # Column doesn't exist, add it
                await conn.execute(text("ALTER TABLE predictions ADD COLUMN photo_path VARCHAR(500)"))
                await conn.commit()
                
            # Check user_request column
            try:
                await conn.execute(text("SELECT user_request FROM predictions LIMIT 1"))
            except Exception:
                # Column doesn't exist, add it
                await conn.execute(text("ALTER TABLE predictions ADD COLUMN user_request TEXT"))
                await conn.commit()
                
            # Check if prediction_photos table exists (simple check)
            # If not, create all tables again (safe since create_all checks persistence)
            # But create_all runs in create_tables.
            # We can rely on create_tables running on startup.
            # But let's add a log measure here if we want to be explicit.
            pass
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session."""
        async with self.async_session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def close(self) -> None:
        """Close database connection."""
        await self.engine.dispose()


# Global database manager instance
db_manager = DatabaseManager(config.database_url)