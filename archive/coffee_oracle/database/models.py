"""Database models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """User model."""
    
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(),
        nullable=False
    )
    
    # Relationship
    predictions: Mapped[list["Prediction"]] = relationship(
        "Prediction", 
        back_populates="user",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"


class Prediction(Base):
    """Prediction model."""
    
    __tablename__ = "predictions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    photo_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user_request: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prediction_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="predictions")
    photos: Mapped[list["PredictionPhoto"]] = relationship(
        "PredictionPhoto",
        back_populates="prediction",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<Prediction(id={self.id}, user_id={self.user_id}, created_at={self.created_at})>"


class PredictionPhoto(Base):
    """Prediction photo model."""
    
    __tablename__ = "prediction_photos"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("predictions.id", ondelete="CASCADE"), 
        nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationship
    prediction: Mapped["Prediction"] = relationship("Prediction", back_populates="photos")
    
    def __repr__(self) -> str:
        return f"<PredictionPhoto(id={self.id}, prediction_id={self.prediction_id}, file_path='{self.file_path}')>"


class BotSettings(Base):
    """Bot settings model for storing configurable parameters."""
    
    __tablename__ = "bot_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<BotSettings(key='{self.key}', value='{self.value[:50]}...')>"
