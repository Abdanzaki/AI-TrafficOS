"""Comprehensive security hardening test suite for Phase 11 production readiness.

Validates:
1. SECRET_KEY fail-fast enforcement in production (ENV=production).
2. CORS_ORIGINS fail-fast enforcement in production (prohibiting wildcard and localhost).
3. JWT validation: expired tokens rejected, tampered tokens rejected.
4. Refresh token rotation: single-use enforcement, old token invalidated on use, replay rejected.
5. In-memory and Redis-backed rate limiting with 429 Too Many Requests and Retry-After headers.
6. Audit logging of security events: failed logins, RBAC denials, privileged actions, role changes.
7. Analyst read-only enforcement: all privileged mutation endpoints return 403 Forbidden.
8. Physical signal hardware control disabled guard: SIGNAL_HARDWARE_ENABLED=False blocks commands.
"""

from datetime import datetime, timedelta, timezone
import pytest
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import AsyncSessionLocal, engine
from app.core.rate_limit import in_memory_limiter
from app.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.main import create_app
from app.models.audit import AuditLog
from app.models.auth import Role, User
from app.services.control.hardware import (
    PhysicalHardwareControlDisabledError,
    dispatch_hardware_signal_command,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear in-memory rate limiter buckets before and after each test."""
    in_memory_limiter.reset()
    yield
    in_memory_limiter.reset()


# ==============================================================================
# 1. SECRET_KEY & CORS Hardening Tests
# ==============================================================================


def test_secret_key_fail_fast_in_production():
    """Verify that in production (ENV=production), missing or insecure SECRET_KEY fails fast."""
    # 1. Unset or empty SECRET_KEY fails
    with pytest.raises(ValueError, match="SECRET_KEY must be explicitly set"):
        Settings(
            ENV="production",
            SECRET_KEY="",
            CORS_ORIGINS=["https://app.trafficos.io"],
            _env_file=None,
        )

    # 2. Insecure placeholder SECRET_KEY fails
    with pytest.raises(ValueError, match="SECRET_KEY must be explicitly set"):
        Settings(
            ENV="production",
            SECRET_KEY="dev-secret-key-change-in-production-trafficos-2026",
            CORS_ORIGINS=["https://app.trafficos.io"],
            _env_file=None,
        )

    # 3. Short SECRET_KEY (<32 chars) fails
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(
            ENV="production",
            SECRET_KEY="too-short-secret-key",
            CORS_ORIGINS=["https://app.trafficos.io"],
            _env_file=None,
        )

    # 4. Valid 64-char key in production succeeds
    valid_key = "a" * 64
    prod_settings = Settings(
        ENV="production",
        SECRET_KEY=valid_key,
        CORS_ORIGINS=["https://app.trafficos.io"],
        _env_file=None,
    )
    assert prod_settings.SECRET_KEY == valid_key


def test_cors_origins_fail_fast_in_production():
    """Verify that in production (ENV=production), wildcard and localhost CORS are rejected."""
    valid_key = "x" * 64

    # 1. Wildcard "*" rejected in production
    with pytest.raises(ValueError, match="Wildcard '\\*' CORS origin is strictly prohibited"):
        Settings(
            ENV="production",
            SECRET_KEY=valid_key,
            CORS_ORIGINS=["*"],
            _env_file=None,
        )

    # 2. Default localhost only rejected in production
    with pytest.raises(ValueError, match="Default localhost origin cannot be used"):
        Settings(
            ENV="production",
            SECRET_KEY=valid_key,
            CORS_ORIGINS=["http://localhost:3000"],
            _env_file=None,
        )

    # 3. Explicit production domain accepted
    s = Settings(
        ENV="production",
        SECRET_KEY=valid_key,
        CORS_ORIGINS=["https://trafficos.example.com"],
        _env_file=None,
    )
    assert s.CORS_ORIGINS == ["https://trafficos.example.com"]


# ==============================================================================
# 2. JWT & Refresh Token Rotation Tests
# ==============================================================================


def test_token_validation_rejects_expired_and_tampered():
    """Verify that decode_token rejects expired and tampered tokens."""
    from app.core.config import settings

    # 1. Expired token raises ExpiredSignatureError
    expired_token = create_access_token(
        user_id=1,
        role="analyst",
        expires_delta=timedelta(seconds=-10),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired_token)

    # 2. Tampered signature raises InvalidSignatureError
    valid_token = create_access_token(user_id=1, role="analyst")
    tampered_token = valid_token[:-5] + ("abcde" if valid_token[-5:] != "abcde" else "12345")
    with pytest.raises(jwt.PyJWTError):
        decode_token(tampered_token)

    # 3. Token signed with wrong secret raises InvalidSignatureError
    wrong_token = jwt.encode(
        {"sub": "1", "role": "analyst", "type": "access", "exp": 9999999999},
        "wrong-secret-key-that-does-not-match-settings",
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.PyJWTError):
        decode_token(wrong_token)


@pytest.mark.anyio
async def test_refresh_token_rotation_and_invalidation(async_client: AsyncClient, test_users: dict):
    """Verify refresh token rotation: old refresh token is invalidated on use and cannot be replayed."""
    analyst_token = test_users["analyst"]["token"]

    # 1. Log in to get a fresh refresh token
    login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@trafficos.io", "password": "adminpassword123"},
    )
    assert login_resp.status_code == 200
    first_refresh = login_resp.json()["refresh_token"]

    # 2. First refresh: succeeds and rotates tokens
    rotate_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert rotate_resp.status_code == 200
    new_tokens = rotate_resp.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens
    second_refresh = new_tokens["refresh_token"]
    assert second_refresh != first_refresh

    # 3. Replay of old refresh token: MUST fail with 401
    replay_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert replay_resp.status_code == 401
    assert "revoked" in replay_resp.json()["detail"].lower() or "used" in replay_resp.json()["detail"].lower()

    # 4. Using the newly rotated token works
    second_rotate_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second_refresh},
    )
    assert second_rotate_resp.status_code == 200


# ==============================================================================
# 3. Rate Limiting Tests
# ==============================================================================


@pytest.mark.anyio
async def test_rate_limiting_on_auth_endpoint(async_client: AsyncClient):
    """Verify rate limiter blocks rapid brute force requests with 429 Too Many Requests."""
    from app.core.rate_limit import in_memory_limiter
    from app.realtime import get_bus

    test_ip = "192.168.100.99"
    headers = {"X-Forwarded-For": test_ip}

    key = f"rl:auth:{test_ip}"
    in_memory_limiter.reset(key)

    # Pre-populate bucket with 60 requests in memory and Redis (if connected)
    now = datetime.now(timezone.utc).timestamp()
    for _ in range(60):
        in_memory_limiter._history[key].append(now)

    bus = get_bus()
    if bus.is_connected and bus._redis is not None:
        pipe = bus._redis.pipeline()
        for i in range(60):
            pipe.zadd(f"trafficos:{key}", {f"{now}_{i}": now})
        await pipe.execute()

    # The 61st request must trigger 429
    resp = await async_client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": "nonexistent@example.com", "password": "wrong"},
    )
    assert resp.status_code == 429
    assert "Rate limit exceeded" in resp.json()["detail"]
    assert "Retry-After" in resp.headers

    # Teardown Redis key
    if bus.is_connected and bus._redis is not None:
        await bus._redis.delete(f"trafficos:{key}")


# ==============================================================================
# 4. Audit Logging Coverage Tests
# ==============================================================================


@pytest.mark.anyio
async def test_audit_logging_on_login_failure_and_rbac_denial(
    async_client: AsyncClient,
    test_users: dict,
    db_session: AsyncSession,
):
    """Verify security audit logs are recorded for login failures and RBAC denials."""
    # 1. Login failure (bad password)
    fail_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@trafficos.io", "password": "WrongPassword999!"},
    )
    assert fail_resp.status_code == 401

    # Check audit log for auth.login_failed
    res = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "auth.login_failed")
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    failed_log = res.scalar_one_or_none()
    assert failed_log is not None
    assert failed_log.details.get("reason") == "invalid_credentials"

    # 2. RBAC denial: analyst attempts to access admin users endpoint
    analyst_token = test_users["analyst"]["token"]
    denied_resp = await async_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert denied_resp.status_code == 403

    # Check audit log for rbac.denied
    res = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "rbac.denied")
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    rbac_log = res.scalar_one_or_none()
    assert rbac_log is not None
    assert rbac_log.actor_user_id == test_users["analyst"]["id"]
    assert rbac_log.details.get("path") == "/api/v1/users"
    assert rbac_log.details.get("user_role") == "analyst"


@pytest.mark.anyio
async def test_audit_logging_on_user_role_change(
    async_client: AsyncClient,
    test_users: dict,
    db_session: AsyncSession,
):
    """Verify that updating a user's role records a user.role_changed audit log entry."""
    admin_token = test_users["admin"]["token"]
    officer_id = test_users["officer"]["id"]

    # Admin changes officer's role to analyst
    patch_resp = await async_client.patch(
        f"/api/v1/users/{officer_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role_name": "analyst"},
    )
    assert patch_resp.status_code == 200

    # Verify audit log contains user.role_changed
    res = await db_session.execute(
        select(AuditLog)
        .where(
            AuditLog.action == "user.role_changed",
            AuditLog.entity_id == officer_id,
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    role_change_log = res.scalar_one_or_none()
    assert role_change_log is not None
    assert role_change_log.details.get("new_role") == "analyst"


# ==============================================================================
# 5. Analyst Read-Only RBAC Enforcement Tests
# ==============================================================================


@pytest.mark.anyio
async def test_analyst_cannot_execute_privileged_mutations(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify that the analyst role CANNOT execute any privileged mutation endpoint (all return 403)."""
    headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    # 1. Incidents
    # POST /api/v1/incidents
    r = await async_client.post("/api/v1/incidents", headers=headers, json={"description": "Test"})
    assert r.status_code == 403, f"POST /incidents returned {r.status_code}"

    # PATCH /api/v1/incidents/1
    r = await async_client.patch("/api/v1/incidents/1", headers=headers, json={"status": "resolved"})
    assert r.status_code == 403, f"PATCH /incidents/1 returned {r.status_code}"

    # DELETE /api/v1/incidents/1
    r = await async_client.delete("/api/v1/incidents/1", headers=headers)
    assert r.status_code == 403, f"DELETE /incidents/1 returned {r.status_code}"

    # 2. Signals
    # POST /api/v1/signals
    r = await async_client.post("/api/v1/signals", headers=headers, json={"intersection_id": 1, "code": "SIG-X"})
    assert r.status_code == 403, f"POST /signals returned {r.status_code}"

    # PATCH /api/v1/signals/1
    r = await async_client.patch("/api/v1/signals/1", headers=headers, json={"status": "inactive"})
    assert r.status_code == 403, f"PATCH /signals/1 returned {r.status_code}"

    # DELETE /api/v1/signals/1
    r = await async_client.delete("/api/v1/signals/1", headers=headers)
    assert r.status_code == 403, f"DELETE /signals/1 returned {r.status_code}"

    # POST /api/v1/signals/1/override
    r = await async_client.post("/api/v1/signals/1/override", headers=headers, json={"state": "red"})
    assert r.status_code == 403, f"POST /signals/1/override returned {r.status_code}"

    # POST /api/v1/signals/1/phases
    r = await async_client.post(
        "/api/v1/signals/1/phases",
        headers=headers,
        json={"name": "P1", "phase_order": 1, "duration_seconds": 30, "state": "green"},
    )
    assert r.status_code == 403, f"POST /signals/1/phases returned {r.status_code}"

    # PATCH /api/v1/phases/1
    r = await async_client.patch("/api/v1/phases/1", headers=headers, json={"state": "red"})
    assert r.status_code == 403, f"PATCH /phases/1 returned {r.status_code}"

    # DELETE /api/v1/phases/1
    r = await async_client.delete("/api/v1/phases/1", headers=headers)
    assert r.status_code == 403, f"DELETE /phases/1 returned {r.status_code}"

    # 3. Control & Decisions
    # POST /api/v1/control/optimize-signals
    r = await async_client.post("/api/v1/control/optimize-signals", headers=headers, json={"intersection_id": 1, "phase_demands": []})
    assert r.status_code == 403, f"POST /control/optimize-signals returned {r.status_code}"

    # POST /api/v1/control/emergency/prioritize
    r = await async_client.post(
        "/api/v1/control/emergency/prioritize",
        headers=headers,
        json={"emergency_event_id": 1, "destination_intersection_id": 2},
    )
    assert r.status_code == 403, f"POST /control/emergency/prioritize returned {r.status_code}"

    # POST /api/v1/control/emergency/restore
    r = await async_client.post("/api/v1/control/emergency/restore", headers=headers, json={"emergency_event_id": 1})
    assert r.status_code == 403, f"POST /control/emergency/restore returned {r.status_code}"

    # POST /api/v1/control/decisions/1/apply
    r = await async_client.post("/api/v1/control/decisions/1/apply", headers=headers)
    assert r.status_code == 403, f"POST /control/decisions/1/apply returned {r.status_code}"

    # POST /api/v1/control/decisions/1/revert
    r = await async_client.post("/api/v1/control/decisions/1/revert", headers=headers)
    assert r.status_code == 403, f"POST /control/decisions/1/revert returned {r.status_code}"

    # 4. User management (all endpoints 403)
    # GET /api/v1/users
    r = await async_client.get("/api/v1/users", headers=headers)
    assert r.status_code == 403

    # POST /api/v1/users
    r = await async_client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "u@example.com", "password": "Password123!", "full_name": "U"},
    )
    assert r.status_code == 403

    # PATCH /api/v1/users/1
    r = await async_client.patch("/api/v1/users/1", headers=headers, json={"full_name": "U"})
    assert r.status_code == 403

    # DELETE /api/v1/users/1
    r = await async_client.delete("/api/v1/users/1", headers=headers)
    assert r.status_code == 403


# ==============================================================================
# 6. Physical Signal Control Disabled Tests
# ==============================================================================


def test_physical_signal_hardware_guard():
    """Verify that physical signal control is disabled by default and cannot be actuated."""
    from app.core.config import settings

    # 1. Config flag defaults to False
    assert settings.SIGNAL_HARDWARE_ENABLED is False

    # 2. Dispatching a hardware signal command raises PhysicalHardwareControlDisabledError
    with pytest.raises(PhysicalHardwareControlDisabledError, match="Physical signal hardware control is disabled"):
        dispatch_hardware_signal_command(
            signal_id=101,
            command="SET_PHASE_GREEN",
            parameters={"phase_id": 1},
        )
