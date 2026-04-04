"""Модуль аутентификации админ-панели.

Реализует JWT-аутентификацию через httpOnly cookies,
управление суперадмином при старте, проверку ролей
(superadmin, restricted, partner).
"""

import datetime
from typing import Annotated, Optional

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.models import AdminUser


def create_access_token(
    user_id: int,
    username: str,
    expiry: datetime.timedelta = datetime.timedelta(hours=24),
) -> str:
    """Создание JWT-токена доступа.

    Args:
        user_id: ID пользователя AdminUser.
        username: Логин пользователя.
        expiry: Время жизни токена (по умолчанию 24 часа).

    Returns:
        Закодированный JWT-токен.
    """
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.datetime.utcnow() + expiry,
    }
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


async def ensure_superadmin() -> None:
    """Синхронизация суперадмина с переменными окружения.

    Создаёт суперадмина, если он отсутствует, или обновляет хеш пароля,
    если ADMIN_PASSWORD был изменён. Вызывается один раз при старте приложения.
    """
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.username == config.admin_username)
        result = await session.execute(stmt)
        superadmin = result.scalar_one_or_none()

        env_password = config.admin_password.encode("utf-8")

        if superadmin is None:
            hashed = bcrypt.hashpw(env_password, bcrypt.gensalt()).decode("utf-8")
            superadmin = AdminUser(
                username=config.admin_username,
                password_hash=hashed,
                role="superadmin",
            )
            session.add(superadmin)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
        elif not bcrypt.checkpw(env_password, superadmin.password_hash.encode("utf-8")):
            superadmin.password_hash = bcrypt.hashpw(
                env_password, bcrypt.gensalt()
            ).decode("utf-8")
            await session.commit()


async def authenticate_admin(
    access_token: Annotated[Optional[str], Cookie()] = None,
) -> AdminUser:
    """Аутентификация пользователя админ-панели через JWT cookie.

    Проверяет наличие и валидность JWT-токена из cookie access_token.
    Возвращает объект AdminUser для любой роли (superadmin, restricted, partner).

    Args:
        access_token: JWT-токен из cookie.

    Returns:
        Объект AdminUser авторизованного пользователя.

    Raises:
        HTTPException 401: Если токен отсутствует, невалиден или пользователь не найден.
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не авторизован",
        )

    try:
        payload = jwt.decode(access_token, config.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
        )

    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пользователь не найден",
            )

        return user


async def require_admin_role(
    user: Annotated[AdminUser, Depends(authenticate_admin)],
) -> AdminUser:
    """Проверка, что пользователь является администратором (не партнёром).

    Используется как зависимость для защиты страниц админ-панели,
    к которым партнёры не должны иметь доступа (дашборд, пользователи,
    предсказания, подписки, настройки).

    Args:
        user: Авторизованный пользователь из authenticate_admin.

    Returns:
        Объект AdminUser, если роль допустима.

    Raises:
        HTTPException 403: Если пользователь является партнёром.
    """
    if user.role == "partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён. Партнёры имеют доступ только к кабинету партнёра.",
        )
    return user


async def require_superadmin_role(
    user: Annotated[AdminUser, Depends(authenticate_admin)],
) -> AdminUser:
    """Проверка, что пользователь является суперадмином.

    Используется для защиты критичных эндпоинтов: настройки,
    управление VIP, ручное завершение платежей, CRUD админов и партнёров.

    Args:
        user: Авторизованный пользователь из authenticate_admin.

    Returns:
        Объект AdminUser, если роль superadmin.

    Raises:
        HTTPException 403: Если пользователь не superadmin.
    """
    if user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён. Требуется роль суперадмина.",
        )
    return user
