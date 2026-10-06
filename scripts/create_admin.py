#!/usr/bin/env python3
"""CLI utility to create an initial admin user or promote an existing user to admin."""

import argparse
import asyncio
from pathlib import Path
import sys

# Ensure backend directory is in sys.path for app module imports
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sqlalchemy import select

from app.core.audit import log_audit
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.auth import Role, User


async def create_or_promote_admin(email: str, password: str, name: str) -> None:
    """Create a new admin user or promote an existing user to admin."""
    normalized_email = email.strip().lower()

    async with AsyncSessionLocal() as db:
        role_stmt = select(Role).where(Role.name == "admin")
        admin_role = (await db.execute(role_stmt)).scalars().first()
        if not admin_role:
            print("Error: Role 'admin' was not found in the database.", file=sys.stderr)
            sys.exit(1)

        user_stmt = select(User).where(User.email == normalized_email)
        user = (await db.execute(user_stmt)).scalars().first()

        if user:
            user.role_id = admin_role.id
            user.is_active = True
            user.hashed_password = hash_password(password)
            user.full_name = name
            await log_audit(
                db=db,
                action="user.promoted_to_admin",
                actor_user_id=user.id,
                entity_type="user",
                entity_id=user.id,
                details={"email": normalized_email, "role": "admin"},
            )
            await db.commit()
            print(f"Promoted existing user {normalized_email} to admin successfully (ID: {user.id}).")
        else:
            new_user = User(
                email=normalized_email,
                hashed_password=hash_password(password),
                full_name=name,
                role_id=admin_role.id,
                is_active=True,
            )
            db.add(new_user)
            await db.flush()

            await log_audit(
                db=db,
                action="user.created_admin",
                actor_user_id=new_user.id,
                entity_type="user",
                entity_id=new_user.id,
                details={"email": normalized_email, "role": "admin"},
            )
            await db.commit()
            print(f"Created new admin user {normalized_email} successfully (ID: {new_user.id}).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an initial admin user or promote an existing user to admin."
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Admin user email address",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="Admin user password (min 8 chars recommended)",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Admin user full name",
    )
    args = parser.parse_args()

    asyncio.run(create_or_promote_admin(email=args.email, password=args.password, name=args.name))


if __name__ == "__main__":
    main()
