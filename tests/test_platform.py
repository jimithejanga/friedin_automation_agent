import uuid
import pytest
from fastapi import Depends, HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, String, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Settings, get_settings
from app.main import app, create_app
from app.platform.audit import AuditLogger, mask_pii, mask_string
from app.platform.auth import (
    AuthenticatedUser,
    Role,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.platform.database import Base, GUID, get_db_session, get_engine


def test_settings_loading():
    settings = get_settings()
    assert settings.APP_NAME == "CMR-Specialist-Automation"
    assert settings.ENVIRONMENT in ("development", "staging", "production", "testing")
    assert settings.PORT == 8000
    assert settings.EMBEDDING_DIM == 1536


def test_password_hashing():
    raw_password = "super-secret-password-123"
    hashed = hash_password(raw_password)
    assert hashed != raw_password
    assert verify_password(raw_password, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_jwt_generation_and_decoding():
    user_id = uuid.uuid4()
    email = "specialist@frieden.ng"
    role = Role.SUPPORT

    token = create_access_token(subject=user_id, role=role, email=email)
    assert isinstance(token, str)

    payload = decode_access_token(token)
    assert payload.sub == str(user_id)
    assert payload.email == email
    assert payload.role == Role.SUPPORT


def test_audit_pii_masking():
    raw_bvn = "22334455667"
    masked_bvn = mask_string(f"User BVN is {raw_bvn}")
    assert raw_bvn not in masked_bvn
    assert "22*******67" in masked_bvn

    raw_card = "4111222233334444"
    masked_card = mask_string(f"Card number: {raw_card}")
    assert raw_card not in masked_card
    assert "****-****-****-4444" in masked_card

    payload = {
        "user_id": "123",
        "password": "my_cleartext_password",
        "nin": "12345678901",
        "nested": {
            "token": "secret_bearer_token",
            "account": "regular_info",
        },
    }
    cleaned = mask_pii(payload)
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["nested"]["token"] == "[REDACTED]"
    assert cleaned["nested"]["account"] == "regular_info"
    assert "12*******01" in cleaned["nin"]

    event = AuditLogger.log(
        action="TEST_ACTION",
        entity_type="CASE",
        entity_id="case-100",
        actor_id="user-1",
        actor_role=Role.CUSTOMER.value,
        request_id="req-999",
        details=payload,
    )
    assert event.action == "TEST_ACTION"
    assert event.details["password"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_health_endpoint_and_telemetry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health", headers={"X-Request-ID": "custom-trace-id-123"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app"] == "CMR-Specialist-Automation"
        assert data["request_id"] == "custom-trace-id-123"
        assert response.headers.get("X-Request-ID") == "custom-trace-id-123"
        assert "X-Process-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_health_endpoint_generates_request_id_if_omitted():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["request_id"] is not None
        assert response.headers.get("X-Request-ID") == data["request_id"]


@pytest.mark.asyncio
async def test_rbac_authorization():
    # Test App with Protected Routes
    test_app = create_app()

    @test_app.get("/admin-only")
    async def admin_route(user: AuthenticatedUser = Depends(require_roles(Role.ADMIN))):
        return {"authorized": True, "role": user.role}

    admin_token = create_access_token(subject=uuid.uuid4(), role=Role.ADMIN)
    customer_token = create_access_token(subject=uuid.uuid4(), role=Role.CUSTOMER)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        # Without auth header
        res_no_auth = await ac.get("/admin-only")
        assert res_no_auth.status_code == 401

        # Customer accessing Admin route -> 403 Forbidden
        res_forbidden = await ac.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {customer_token}"},
        )
        assert res_forbidden.status_code == 403

        # Admin accessing Admin route -> 200 OK
        res_allowed = await ac.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_allowed.status_code == 200
        assert res_allowed.json()["authorized"] is True


@pytest.mark.asyncio
async def test_database_base_and_guid():
    # Define a test model to verify DeclarativeBase and GUID type
    class DummyEntity(Base):
        __tablename__ = "dummy_entities"
        name = Column(String(50), nullable=False)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = AsyncSession(engine)
    entity_id = uuid.uuid4()
    dummy = DummyEntity(id=entity_id, name="Test Document")
    async with async_session as session:
        session.add(dummy)
        await session.commit()

        result = await session.execute(select(DummyEntity).where(DummyEntity.id == entity_id))
        fetched = result.scalar_one()
        assert fetched.id == entity_id
        assert fetched.name == "Test Document"
        assert fetched.created_at is not None
        assert fetched.updated_at is not None

    await engine.dispose()
