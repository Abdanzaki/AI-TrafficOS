"""Test suite for JWT authentication, RBAC, user management, and audit logging."""

import uuid
from httpx import ASGITransport, AsyncClient
import pytest

from app.core.database import engine
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.main import create_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_client():
    """Fixture providing an async HTTP client sharing the test event loop."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    await engine.dispose()




def test_password_hashing():
    """Verify bcrypt hash generation and verification."""
    password = "SuperSecurePassword123!"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


def test_jwt_token_creation_and_decoding():
    """Verify access and refresh token creation and claims decoding."""
    user_id = 999
    role = "traffic_officer"

    access_token = create_access_token(user_id=user_id, role=role)
    decoded_access = decode_token(access_token)
    assert decoded_access["sub"] == str(user_id)
    assert decoded_access["role"] == role
    assert decoded_access["type"] == "access"

    refresh_token = create_refresh_token(user_id=user_id)
    decoded_refresh = decode_token(refresh_token)
    assert decoded_refresh["sub"] == str(user_id)
    assert decoded_refresh["type"] == "refresh"


@pytest.mark.anyio
async def test_auth_full_flow(async_client: AsyncClient):
    """End-to-end test of register, login, auth/me, and refresh."""
    unique_suffix = uuid.uuid4().hex[:8]
    email = f"analyst_{unique_suffix}@example.com"
    password = "SecurePassword123"
    full_name = "Test Analyst"

    # 1. Register analyst (201)
    reg_resp = await async_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["email"] == email
    assert user_data["role_name"] == "analyst"
    assert user_data["is_active"] is True
    user_id = user_data["id"]

    # 2. Duplicate registration rejected (409)
    dup_resp = await async_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert dup_resp.status_code == 409

    # 3. Invalid email validation (422)
    invalid_email_resp = await async_client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": password, "full_name": full_name},
    )
    assert invalid_email_resp.status_code == 422
    assert "detail" in invalid_email_resp.json()

    # 4. Short password validation (422)
    short_pw_resp = await async_client.post(
        "/api/v1/auth/register",
        json={"email": f"short_{unique_suffix}@example.com", "password": "123", "full_name": full_name},
    )
    assert short_pw_resp.status_code == 422

    # 5. Login wrong password (401)
    wrong_pw_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert wrong_pw_resp.status_code == 401

    # 6. Login valid credentials (200)
    login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # 7. GET /auth/me with token (200)
    me_resp = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] == user_id
    assert me_resp.json()["role_name"] == "analyst"

    # 8. GET /auth/me without token (401)
    no_token_resp = await async_client.get("/api/v1/auth/me")
    assert no_token_resp.status_code == 401

    # 9. POST /auth/refresh (200)
    refresh_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens

    # 10. POST /auth/refresh with invalid token (401)
    bad_refresh_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid.jwt.token"},
    )
    assert bad_refresh_resp.status_code == 401


@pytest.mark.anyio
async def test_rbac_and_user_management(async_client: AsyncClient):
    """Test RBAC role guard and admin user management endpoints."""
    # Register analyst
    analyst_email = f"analyst_{uuid.uuid4().hex[:8]}@example.com"
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": analyst_email, "password": "Password123!", "full_name": "Analyst"},
    )
    analyst_login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": analyst_email, "password": "Password123!"},
    )
    analyst_login = analyst_login_resp.json()
    analyst_token = analyst_login["access_token"]

    # Analyst cannot access GET /users (403)
    analyst_forbidden = await async_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert analyst_forbidden.status_code == 403

    # Admin login
    admin_email = "admin@trafficos.io"
    admin_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": "adminpassword123"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]

    # Admin can list users (200)
    list_resp = await async_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200
    users_page = list_resp.json()
    assert "items" in users_page
    assert users_page["total"] >= 1

    # Admin creates user with explicit role (201)
    officer_email = f"officer_{uuid.uuid4().hex[:8]}@example.com"
    create_resp = await async_client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": officer_email,
            "password": "Password123!",
            "full_name": "Officer Sarah",
            "role_name": "traffic_officer",
        },
    )
    assert create_resp.status_code == 201
    officer_data = create_resp.json()
    assert officer_data["role_name"] == "traffic_officer"
    officer_id = officer_data["id"]

    # Admin updates user (200)
    patch_resp = await async_client.patch(
        f"/api/v1/users/{officer_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"full_name": "Officer Sarah Senior"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["full_name"] == "Officer Sarah Senior"

    # Admin deactivates user (200)
    delete_resp = await async_client.delete(
        f"/api/v1/users/{officer_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["is_active"] is False

    # Deactivated user cannot log in (401)
    deactivated_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": officer_email, "password": "Password123!"},
    )
    assert deactivated_login.status_code == 401
    assert "inactive" in deactivated_login.json()["detail"].lower()
