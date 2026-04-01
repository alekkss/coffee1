"""Модели базы данных.

Содержит SQLAlchemy-модели для всех сущностей приложения:
пользователи, предсказания, фото, платежи, настройки, администраторы.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """Модель пользователя.

    Хранит данные пользователей из всех поддерживаемых мессенджеров.
    Поле source определяет платформу-источник ('tg' для Telegram,
    'max' для MAX). Уникальность обеспечивается парой
    (telegram_id, source), что исключает коллизии ID между платформами.
    """

    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("telegram_id", "source", name="uq_users_telegram_id_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="tg"
    )  # 'tg' — Telegram, 'max' — MAX
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Поля подписки
    subscription_type: Mapped[str] = mapped_column(
        String(50), default="free", nullable=False
    )  # free, premium, vip
    subscription_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vip_reason: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Причина VIP-статуса (тестер, партнёр и т.д.)

    # Поля рекуррентных платежей
    recurring_payment_enabled: Mapped[bool] = mapped_column(
        Integer, default=0, nullable=False
    )  # Автопродление включено (0/1 для совместимости с SQLite)
    telegram_recurring_payment_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # ID рекуррентного платежа для отмены

    # Мягкое удаление
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Связи
    predictions: Mapped[list["Prediction"]] = relationship(
        "Prediction",
        back_populates="user",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="user",
    )

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, telegram_id={self.telegram_id}, "
            f"source='{self.source}', username='{self.username}')>"
        )


class Prediction(Base):
    """Модель предсказания."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    photo_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user_request: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prediction_text: Mapped[str] = mapped_column(Text, nullable=False)
    subscription_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # Тип подписки на момент предсказания (free, premium, vip)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Связи
    user: Mapped["User"] = relationship("User", back_populates="predictions")
    photos: Mapped[list["PredictionPhoto"]] = relationship(
        "PredictionPhoto",
        back_populates="prediction",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Prediction(id={self.id}, user_id={self.user_id}, "
            f"created_at={self.created_at})>"
        )


class PredictionPhoto(Base):
    """Модель фотографии предсказания."""

    __tablename__ = "prediction_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Связи
    prediction: Mapped["Prediction"] = relationship(
        "Prediction", back_populates="photos"
    )

    def __repr__(self) -> str:
        return (
            f"<PredictionPhoto(id={self.id}, prediction_id={self.prediction_id}, "
            f"file_path='{self.file_path}')>"
        )


class BotSettings(Base):
    """Модель настроек бота для хранения конфигурируемых параметров."""

    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default="admin"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<BotSettings(key='{self.key}', value='{self.value[:50]}...')>"


class AdminUser(Base):
    """Модель администратора для контроля доступа на основе ролей."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="restricted"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<AdminUser(id={self.id}, username='{self.username}', "
            f"role='{self.role}')>"
        )


class Payment(Base):
    """Модель истории платежей за подписку."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # Сумма в копейках
    label: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )  # Уникальный идентификатор платежа для отслеживания
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )  # YooKassa payment ID
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )  # pending, completed, failed
    is_recurring: Mapped[bool] = mapped_column(
        Integer, default=0, nullable=False
    )  # Рекуррентный платёж (0/1 для совместимости с SQLite)
    telegram_recurring_payment_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # ID рекуррентного платежа Telegram
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Связи
    user: Mapped["User"] = relationship("User", back_populates="payments")

    def __repr__(self) -> str:
        return (
            f"<Payment(id={self.id}, user_id={self.user_id}, "
            f"amount={self.amount}, status='{self.status}')>"
        )
