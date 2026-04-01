#!/usr/bin/env python3
"""
Script to create admin users.
Usage: python scripts/create_admin.py <username> <password> [--role <role>]
"""

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.models import AdminUser


async def create_user(username: str, password: str, role: str, force: bool = False) -> None:
    """Create a new admin user or update password if --force is set."""
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.username == username)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing and not force:
            print(f"Error: User '{username}' already exists. Use --force to reset password.")
            return

        if existing and force:
            print(f"Resetting password for '{username}'...")
            existing.password_hash = bcrypt.hashpw(
                password.encode('utf-8'), bcrypt.gensalt()
            ).decode('utf-8')
            existing.role = role
            try:
                await session.commit()
                print(f"Password for '{username}' updated successfully!")
            except Exception as e:
                await session.rollback()
                print(f"Error updating user: {e}")
            return

        print(f"Creating user '{username}' with role '{role}'...")

        hashed_bytes = bcrypt.hashpw(
            password.encode('utf-8'), 
            bcrypt.gensalt()
        )
        new_user = AdminUser(
            username=username,
            password_hash=hashed_bytes.decode('utf-8'),
            role=role
        )
        
        session.add(new_user)
        try:
            await session.commit()
            print(f"User '{username}' created successfully!")
        except Exception as e:
            await session.rollback()
            print(f"Error creating user: {e}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create Coffee Oracle admin user")
    parser.add_argument("username", help="Username for login")
    parser.add_argument("password", help="Password for login")
    parser.add_argument(
        "--role", 
        choices=["superadmin", "restricted"], 
        default="restricted",
        help="User role (default: restricted)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reset password if user already exists"
    )
    
    args = parser.parse_args()
    
    try:
        await create_user(args.username, args.password, args.role, args.force)
    finally:
        await db_manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
