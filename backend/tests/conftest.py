"""Pytest configuration and shared test fixtures for AI TrafficOS.

Provides event loop configuration, async HTTP client, database session,
and role-based authenticated test user accounts (admin, officer, analyst).
"""

import uuid
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.main import create_app
from app.models.auth import Role, User


@pytest.fixture
def anyio_backend() -> str:
    """Designate asyncio as the anyio async testing backend."""
    return "asyncio"


@pytest.fixture
async def async_client():
    """Async HTTP client fixture communicating with test ASGI application."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncSession:
    """Async SQLAlchemy database session fixture for direct model interactions."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def test_users(async_client: AsyncClient) -> dict[str, dict[str, str | int]]:
    """Fixture that provisions admin, officer, and analyst users and returns auth tokens."""
    uid = uuid.uuid4().hex[:8]
    password = "TestPassword123!"

    # 1. Admin login or create
    admin_email = "admin@trafficos.io"
    admin_login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": "adminpassword123"},
    )
    if admin_login_resp.status_code == 200:
        admin_token = admin_login_resp.json()["access_token"]
        me_resp = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_id = me_resp.json()["id"]
    else:
        async with AsyncSessionLocal() as db:
            admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalars().first()
            existing_admin = (await db.execute(select(User).where(User.email == admin_email))).scalars().first()
            if not existing_admin:
                admin_u = User(
                    email=admin_email,
                    hashed_password=hash_password("adminpassword123"),
                    full_name="Test Admin",
                    role_id=admin_role.id,
                    is_active=True,
                )
                db.add(admin_u)
                await db.commit()
                await db.refresh(admin_u)
                admin_id = admin_u.id
            else:
                existing_admin.hashed_password = hash_password("adminpassword123")
                existing_admin.is_active = True
                await db.commit()
                await db.refresh(existing_admin)
                admin_id = existing_admin.id

        admin_login = await async_client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "adminpassword123"},
        )
        admin_token = admin_login.json()["access_token"]

    # 2. Officer user
    officer_email = f"officer_{uid}@trafficos.io"
    officer_resp = await async_client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": officer_email,
            "password": password,
            "full_name": "Traffic Officer",
            "role_name": "traffic_officer",
        },
    )
    assert officer_resp.status_code == 201, officer_resp.text
    officer_id = officer_resp.json()["id"]

    officer_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": officer_email, "password": password},
    )
    assert officer_login.status_code == 200, officer_login.text
    officer_token = officer_login.json()["access_token"]

    # 3. Analyst user
    analyst_email = f"analyst_{uid}@trafficos.io"
    analyst_resp = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": analyst_email,
            "password": password,
            "full_name": "Traffic Analyst",
        },
    )
    assert analyst_resp.status_code == 201, analyst_resp.text
    analyst_id = analyst_resp.json()["id"]

    analyst_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": analyst_email, "password": password},
    )
    assert analyst_login.status_code == 200, analyst_login.text
    analyst_token = analyst_login.json()["access_token"]

    return {
        "admin": {"token": admin_token, "id": admin_id},
        "officer": {"token": officer_token, "id": officer_id},
        "analyst": {"token": analyst_token, "id": analyst_id},
    }
