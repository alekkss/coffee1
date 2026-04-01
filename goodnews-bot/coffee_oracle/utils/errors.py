"""Custom error classes and error handling utilities."""

from typing import Optional


class CoffeeOracleError(Exception):
    """Base exception for Coffee Oracle application."""
    
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


class DatabaseError(CoffeeOracleError):
    """Database operation error."""
    pass


class OpenAIError(CoffeeOracleError):
    """OpenAI API error."""
    pass


class PhotoProcessingError(CoffeeOracleError):
    """Photo processing error."""
    pass


class ConfigurationError(CoffeeOracleError):
    """Configuration error."""
    pass


class AuthenticationError(CoffeeOracleError):
    """Authentication error."""
    pass


def format_error_message(error: Exception, user_friendly: bool = True) -> str:
    """Format error message for display."""
    
    if isinstance(error, CoffeeOracleError):
        if user_friendly:
            return error.message
        return f"{error.message} - {error.details}" if error.details else error.message
    
    if user_friendly:
        return "Произошла непредвиденная ошибка. Попробуйте позже."
    
    return str(error)