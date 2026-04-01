"""Database models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
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
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(),
        nullable=False
    )
    
    # Subscription fields
    subscription_type: Mapped[str] = mapped_column(
        String(50), default="free", nullable=False
    )  # free, premium, vip
    subscription_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vip_reason: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Reason for VIP status (tester, partner, etc.)
    
    # Recurring payment fields
    recurring_payment_enabled: Mapped[bool] = mapped_column(
        Integer, default=0, nullable=False
    )  # Whether auto-renewal is enabled (stored as 0/1 for SQLite compatibility)
    telegram_recurring_payment_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Telegram's recurring payment ID for cancellation
    
    # Soft delete
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    
    # Relationships
    predictions: Mapped[list["Prediction"]] = relationship(
        "Prediction", 
        back_populates="user"
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="user"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"


class Prediction(Base):
    """Prediction model."""
    
    __tablename__ = "predictions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("users.id"),
        nullable=False
    )
    photo_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user_request: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prediction_text: Mapped[str] = mapped_column(Text, nullable=False)
    subscription_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # Subscription type at the time of prediction (free, premium, vip)
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
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="admin")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<BotSettings(key='{self.key}', value='{self.value[:50]}...')>"


class AdminUser(Base):
    """Admin user model for role-based access control."""
    
    __tablename__ = "admin_users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="restricted")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<AdminUser(id={self.id}, username='{self.username}', role='{self.role}')>"


class Payment(Base):
    """Payment history model for subscription payments."""
    
    __tablename__ = "payments"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("users.id"),
        nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # Amount in kopecks
    label: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )  # Unique payment identifier for tracking
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # YooKassa payment ID
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )  # pending, completed, failed
    is_recurring: Mapped[bool] = mapped_column(
        Integer, default=0, nullable=False
    )  # Whether this is a recurring payment (stored as 0/1 for SQLite compatibility)
    telegram_recurring_payment_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Telegram's recurring payment charge ID
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="payments")
    
    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, user_id={self.user_id}, amount={self.amount}, status='{self.status}')>"
