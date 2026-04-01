"""Admin authentication middleware."""

import datetime
from typing import Annotated, Optional

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.models import AdminUser


def create_access_token(user_id: int, username: str, expiry: datetime.timedelta = datetime.timedelta(hours=24)) -> str:
    """Create JWT access token."""
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.datetime.utcnow() + expiry
    }
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


async def ensure_superadmin() -> None:
    """Ensure superadmin exists with password matching ADMIN_PASSWORD from env.

    Creates the superadmin if missing, or updates the password hash
    if ADMIN_PASSWORD was changed since last startup.
    Should be called once at application startup.
    """
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.username == config.admin_username)
        result = await session.execute(stmt)
        superadmin = result.scalar_one_or_none()

        env_password = config.admin_password.encode('utf-8')

        if superadmin is None:
            hashed = bcrypt.hashpw(env_password, bcrypt.gensalt()).decode('utf-8')
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
        elif not bcrypt.checkpw(env_password, superadmin.password_hash.encode('utf-8')):
            superadmin.password_hash = bcrypt.hashpw(
                env_password, bcrypt.gensalt()
            ).decode('utf-8')
            await session.commit()


async def authenticate_admin(
    access_token: Annotated[Optional[str], Cookie()] = None
) -> AdminUser:
    """Authenticate admin user via JWT cookie."""
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = jwt.decode(access_token, config.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        return user