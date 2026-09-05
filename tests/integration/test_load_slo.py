import asyncio
import time
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.platform.auth import Role, create_access_token
from app.platform.database import Base, get_db_session
from scripts.seed_db import seed_procedural_knowledge, seed_staff_accounts


from sqlalchemy.pool import StaticPool


@pytest.fixture
async def async_db():
    """Provides an isolated database seeded with procedural knowledge for load testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with session_maker() as session:
        await seed_staff_accounts(session)
        await seed_procedural_knowledge(session)
        await session.commit()

    yield session_maker, engine

    await engine.dispose()


@pytest.fixture
async def client(async_db):
    """Provides an AsyncClient bound to the FastAPI app with test db session override."""
    session_maker, _ = async_db
    app = create_app()

    async def override_get_db_session():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_simulated_2x_peak_load_slo_targets(client: AsyncClient):
    """PHASE 7 EXIT CHECK:
    Simulates 2x peak load traffic (50+ simultaneous concurrent requests across AI answers,
    support queues, and ops dashboards) and verifies that all SLO targets are met:
    - 0% error rate (monthly availability >= 99.9%)
    - Non-AI endpoint p95 latency < 500 ms
    - AI answer p95 latency < 12 sec
    """
    token = create_access_token(
        subject="00000000-0000-0000-0000-000000000001",
        email="admin@cmr.police.gov.ng",
        role=Role.ADMIN,
    )
    admin_headers = {"Authorization": f"Bearer {token}"}

    ai_latencies = []
    non_ai_latencies = []
    errors = []

    # 1. Worker for Customer AI Questions
    async def request_ai_question(q_idx: int):
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                "/api/v1/customer/questions",
                json={
                    "question": f"What is the clearance turnaround time and fee schedule for car {q_idx}?",
                    "channel": "web",
                },
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            ai_latencies.append(elapsed)
            if resp.status_code != 200:
                errors.append((resp.status_code, resp.text))
        except Exception as exc:
            errors.append((500, str(exc)))

    # 2. Worker for Support Console Queue Queries
    async def request_support_cases(q_idx: int):
        t0 = time.perf_counter()
        try:
            resp = await client.get("/api/v1/support/cases", headers=admin_headers)
            elapsed = (time.perf_counter() - t0) * 1000.0
            non_ai_latencies.append(elapsed)
            if resp.status_code != 200:
                errors.append((resp.status_code, resp.text))
        except Exception as exc:
            errors.append((500, str(exc)))

    # 3. Worker for Ops Dashboard Metrics
    async def request_ops_metrics(q_idx: int):
        t0 = time.perf_counter()
        try:
            resp = await client.get("/api/v1/ops/dashboard", headers=admin_headers)
            elapsed = (time.perf_counter() - t0) * 1000.0
            non_ai_latencies.append(elapsed)
            if resp.status_code != 200:
                errors.append((resp.status_code, resp.text))
        except Exception as exc:
            errors.append((500, str(exc)))

    # 4. Worker for Health Probes
    async def request_health_probe(q_idx: int):
        t0 = time.perf_counter()
        try:
            resp = await client.get("/health/ready")
            elapsed = (time.perf_counter() - t0) * 1000.0
            non_ai_latencies.append(elapsed)
            if resp.status_code != 200:
                errors.append((resp.status_code, resp.text))
        except Exception as exc:
            errors.append((500, str(exc)))

    # Generate 52 concurrent tasks (Simulated 2x peak surge)
    tasks = []
    for i in range(16):
        tasks.append(request_ai_question(i))
        tasks.append(request_support_cases(i))
        tasks.append(request_ops_metrics(i))
        tasks.append(request_health_probe(i))

    total_requests = len(tasks)
    start_time = time.perf_counter()
    await asyncio.gather(*tasks)
    total_duration_sec = time.perf_counter() - start_time

    # Calculate and assert SLO targets
    assert len(errors) == 0, f"Errors encountered during load test: {errors}"
    error_rate = len(errors) / total_requests
    assert error_rate == 0.0, "Service error rate under load must be 0%"

    # Non-AI Latency p95 assertion (< 500 ms)
    assert len(non_ai_latencies) > 0
    non_ai_p95 = float(np.percentile(non_ai_latencies, 95))
    assert non_ai_p95 < 500.0, f"Non-AI p95 latency {non_ai_p95:.2f} ms exceeded SLO target (< 500 ms)"

    # AI Latency p95 assertion (< 12 sec = 12000 ms)
    assert len(ai_latencies) > 0
    ai_p95 = float(np.percentile(ai_latencies, 95))
    assert ai_p95 < 12000.0, f"AI p95 latency {ai_p95:.2f} ms exceeded SLO target (< 12000 ms)"

    throughput_rps = total_requests / total_duration_sec
    assert throughput_rps > 0
