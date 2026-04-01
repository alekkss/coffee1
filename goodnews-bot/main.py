"""Main application entry point."""

import asyncio
import signal
import sys
from typing import Any

import uvicorn

from coffee_oracle.admin.app import app as admin_app
from coffee_oracle.bot.bot import CoffeeOracleBot
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.services.subscription_scheduler import SubscriptionScheduler
from coffee_oracle.utils.logging import setup_logging, get_logger

# Setup logging
setup_logging(level="INFO", log_file="logs/coffee_oracle.log")
logger = get_logger(__name__)


class ApplicationOrchestrator:
    """Main application orchestrator."""
    
    def __init__(self):
        self.bot = CoffeeOracleBot()
        self.admin_server = None
        self.scheduler = None
        self.shutdown_event = asyncio.Event()
    
    async def start_admin_server(self) -> None:
        """Start FastAPI admin server."""
        config_uvicorn = uvicorn.Config(
            admin_app,
            host="0.0.0.0",
            port=config.admin_port,
            log_level="info",
            access_log=True
        )
        
        self.admin_server = uvicorn.Server(config_uvicorn)
        logger.info("Starting admin server on port %d", config.admin_port)
        
        try:
            await self.admin_server.serve()
        except Exception as e:
            logger.error("Admin server error: %s", e)
            raise
    
    async def start_bot(self) -> None:
        """Start Telegram bot."""
        logger.info("Starting Telegram bot")
        
        try:
            await self.bot.start_polling()
        except Exception as e:
            logger.error("Bot error: %s", e)
            raise
    
    async def setup_database(self) -> None:
        """Initialize database."""
        logger.info("Setting up database...")
        try:
            await db_manager.create_tables()
            logger.info("Database setup completed")
            
            # Run migrations
            logger.info("Running database migrations...")
            from coffee_oracle.database.migrations import run_migrations
            async for session in db_manager.get_session():
                await run_migrations(session)
                break  # Only need one session

            # Ensure superadmin exists with current ADMIN_PASSWORD
            from coffee_oracle.admin.auth import ensure_superadmin
            await ensure_superadmin()
            logger.info("Superadmin account synced")
            
        except Exception as e:
            logger.error("Database setup error: %s", e)
            raise
    
    async def start_services(self) -> None:
        """Start all services concurrently."""
        logger.info("Starting Coffee Oracle services...")
        
        # Setup database first
        await self.setup_database()
        
        # Start both services concurrently
        tasks = [
            asyncio.create_task(self.start_bot(), name="telegram_bot"),
            asyncio.create_task(self.start_admin_server(), name="admin_server")
        ]
        
        # Initialize webhook handler with bot instance
        from coffee_oracle.admin.app import init_webhook_handler
        init_webhook_handler(self.bot.bot)

        # Start subscription scheduler
        self.scheduler = SubscriptionScheduler(self.bot.bot)
        await self.scheduler.start()
        
        try:
            # Wait for shutdown signal or any task to complete
            _, pending = await asyncio.wait(
                tasks + [asyncio.create_task(self.shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
        except Exception as e:
            logger.error("Service error: %s", e)
            raise
        finally:
            await self.cleanup()
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("Cleaning up resources...")
        
        try:
            # Stop bot
            await self.bot.stop()
            
            # Stop scheduler
            if self.scheduler:
                await self.scheduler.stop()
            
            # Stop admin server
            if self.admin_server:
                self.admin_server.should_exit = True
            
            # Close database connections
            await db_manager.close()
            
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error("Cleanup error: %s", e)
    
    def signal_handler(self, signum: int, _: Any) -> None:
        """Handle shutdown signals."""
        logger.info("Received signal %d, initiating shutdown...", signum)
        self.shutdown_event.set()


async def main() -> None:
    """Main application function."""
    orchestrator = ApplicationOrchestrator()
    
    # Setup signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, orchestrator.signal_handler)
    
    try:
        await orchestrator.start_services()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error("Application error: %s", e)
        sys.exit(1)
    
    logger.info("Coffee Oracle application stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error("Fatal error: %s", e)
        sys.exit(1)