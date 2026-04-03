"""Logging configuration and utilities."""

import logging
import sys
from pathlib import Path
from typing import Optional


from logging.handlers import RotatingFileHandler

def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
) -> None:
    """Setup application logging."""
    
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Create logs directory if it doesn't exist
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Configure logging
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        # Rotate logs: max 10MB per file, keep 1 backups
        handlers.append(RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024, 
            backupCount=1, 
            encoding='utf-8'
        ))
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=format_string,
        handlers=handlers,
        force=True
    )
    
    # Set specific loggers to appropriate levels
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get logger instance."""
    return logging.getLogger(name)