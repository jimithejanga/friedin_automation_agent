import uuid
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.models import AIRun
from app.cases.models import Case, CaseEvent, CasePriority, CaseStatus, Conversation, Message, MessageSenderType, Person
from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.main import create_app
from app.platform.audit import AuditLogger, DbAuditEvent
from app.platform.auth import Role, create_access_token
from app.platform.database import Base, get_db_session


@pytest.fixture
async def async_db():
    """Provides an isolated in-memory SQLite database for ops dashboard tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
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
        yield session, engine

    await engine.dispose()


@pytest.fixture
async def client(async_db):
    """Provides an AsyncClient bound to the FastAPI app with test db session override."""
    session, _ = async_db
    app = create_app()

    async def override_get_db_session():
        session.expire_all()
        yield session
        await session.commit()

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    app.dependency_overrides.clear()


def make_auth_headers(role: Role) -> dict:
    token = create_access_token(
        subject=str(uuid.uuid4()),
        email=f"{role.value}@cmr.police.gov.ng",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_health_and_readiness_probes(client: AsyncClient):
    """Verify GET /health (liveness) and GET /health/ready (database readiness)."""
    # 1. Liveness
    res_liveness = await client.get("/health")
    assert res_liveness.status_code == 200
    data_liveness = res_liveness.json()
    assert data_liveness["status"] == "ok"
    assert "CMR" in data_liveness["app"]

    # 2. Readiness
    res_ready = await client.get("/health/ready")
    assert res_ready.status_code == 200
    data_ready = res_ready.json()
    assert data_ready["status"] == "ready"
    assert data_ready["database"] == "ready"


@pytest.mark.asyncio
async def test_ops_rbac_access_control(client: AsyncClient):
    """Verify RBAC: CUSTOMER role receives 403 Forbidden; ADMIN, SUPERVISOR, AUDITOR succeed."""
    # 1. Unauthenticated -> 401
    res_anon = await client.get("/api/v1/ops/dashboard")
    assert res_anon.status_code == 401

    # 2. Customer role -> 403 Forbidden
    cust_headers = make_auth_headers(Role.CUSTOMER)
    res_cust = await client.get("/api/v1/ops/dashboard", headers=cust_headers)
    assert res_cust.status_code == 403

    # 3. Support staff -> 403 (Ops is for supervisor, admin, auditor)
    support_headers = make_auth_headers(Role.SUPPORT)
    res_sup = await client.get("/api/v1/ops/dashboard", headers=support_headers)
    assert res_sup.status_code == 403

    # 4. Supervisor -> 200 OK
    supervisor_headers = make_auth_headers(Role.SUPERVISOR)
    res_super = await client.get("/api/v1/ops/dashboard", headers=supervisor_headers)
    assert res_super.status_code == 200

    # 5. Admin -> 200 OK
    admin_headers = make_auth_headers(Role.ADMIN)
    res_admin = await client.get("/api/v1/ops/dashboard", headers=admin_headers)
    assert res_admin.status_code == 200

    # 6. Auditor -> 200 OK
    auditor_headers = make_auth_headers(Role.AUDITOR)
    res_auditor = await client.get("/api/v1/ops/dashboard", headers=auditor_headers)
    assert res_auditor.status_code == 200


@pytest.mark.asyncio
async def test_ops_dashboard_metrics_4_pillars(client: AsyncClient, async_db):
    """Verify aggregated dashboard correctly computes metrics across the 4 pillars:
    Service Health, Customer Flow, AI Quality, Knowledge Base.
    """
    session, _ = async_db

    # Seed Person & Cases
    person = Person(
        full_name="Musa Danladi",
        phone_number="+2348011112222",
        email="musa@example.com",
    )
    session.add(person)
    await session.flush()

    case_active = Case(
        case_number="CMR-CASE-ACTIVE-01",
        person_id=person.id,
        status=CaseStatus.IN_REVIEW,
        priority=CasePriority.HIGH,
        category="STOLEN_VEHICLE_REPORT",
        subject="Active stolen report",
    )
    case_resolved = Case(
        case_number="CMR-CASE-RESOLVED-02",
        person_id=person.id,
        status=CaseStatus.RESOLVED,
        priority=CasePriority.NORMAL,
        category="CLEARANCE_FAILURE",
        subject="Resolved clearance inquiry",
        resolved_at=datetime.now(timezone.utc),
    )
    session.add_all([case_active, case_resolved])
    await session.flush()

    # Seed Conversation & Messages
    conv = Conversation(person_id=person.id, case_id=case_active.id, channel="web")
    session.add(conv)
    await session.flush()

    msg_cust = Message(
        conversation_id=conv.id,
        sender_type=MessageSenderType.CUSTOMER,
        content="Where is my clearance?",
    )
    msg_asst = Message(
        conversation_id=conv.id,
        sender_type=MessageSenderType.ASSISTANT,
        content="Clearance turnaround is 24-48 hours.",
    )
    session.add_all([msg_cust, msg_asst])

    # Seed Knowledge Document with ACTIVE and DRAFT versions
    doc = Document(title="National CMR Standard Procedure")
    session.add(doc)
    await session.flush()

    v_active = DocumentVersion(document_id=doc.id, version_number=1, status=DocumentVersionStatus.ACTIVE)
    v_draft = DocumentVersion(document_id=doc.id, version_number=2, status=DocumentVersionStatus.DRAFT)
    session.add_all([v_active, v_draft])
    await session.flush()

    chunk1 = Chunk(version_id=v_active.id, chunk_index=0, chunk_id_code="Ch-1", content="Text 1", token_count=10)
    chunk2 = Chunk(version_id=v_active.id, chunk_index=1, chunk_id_code="Ch-2", content="Text 2", token_count=20)
    session.add_all([chunk1, chunk2])

    # Seed AI Runs
    ai_run_hit = AIRun(
        model_name="gpt-4o-mini",
        prompt_template_version="v1.0.0",
        intent="INFORMATIONAL",
        query_text="Clearance hours?",
        answer_text="24 to 48 business hours.",
        retrieved_chunks=[{"chunk_id_code": "Ch-1"}],
        citations=[{"document_title": "National CMR Standard Procedure"}],
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        latency_ms=250.0,
        fallback_triggered=False,
    )
    ai_run_fallback = AIRun(
        model_name="gpt-4o-mini",
        prompt_template_version="v1.0.0",
        intent="INFORMATIONAL",
        query_text="Random unknown query",
        answer_text="General guidance.",
        retrieved_chunks=[],
        citations=[],
        input_tokens=80,
        output_tokens=40,
        total_tokens=120,
        latency_ms=180.0,
        fallback_triggered=True,
    )
    session.add_all([ai_run_hit, ai_run_fallback])

    # Seed Audit Events
    await AuditLogger.record_async(
        session=session,
        action="CASE_CREATED",
        entity_type="case",
        entity_id=str(case_active.id),
        actor_role="customer",
        details={"case_number": case_active.case_number},
    )
    await session.commit()

    # Query Dashboard API as Admin
    headers = make_auth_headers(Role.ADMIN)
    resp = await client.get("/api/v1/ops/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Pillar 1: Service Health
    sh = data["service_health"]
    assert sh["status"] == "HEALTHY"
    assert sh["database_ready"] is True
    assert sh["total_requests"] >= 1
    assert sh["slo_availability_target"] == ">= 99.9%"

    # Pillar 2: Customer Flow
    cf = data["customer_flow"]
    assert cf["answers_delivered"] == 1
    assert cf["cases_opened"] == 2
    assert cf["active_cases"] == 1
    assert cf["resolved_cases"] == 1

    # Pillar 3: AI Quality
    aiq = data["ai_quality"]
    assert aiq["total_ai_runs"] == 2
    assert aiq["retrieval_hit_rate_pct"] == 50.0
    assert aiq["fallback_rate_pct"] == 50.0
    assert aiq["total_tokens"] == 270

    # Pillar 4: Knowledge
    km = data["knowledge"]
    assert km["total_documents"] == 1
    assert km["active_versions"] == 1
    assert km["draft_versions"] == 1
    assert km["total_chunks"] == 2


@pytest.mark.asyncio
async def test_ops_audit_log_search_and_pii_masking(client: AsyncClient, async_db):
    """Verify audit logs are searchable with structured filters and guaranteed PII masking."""
    session, _ = async_db

    # Insert audit event with sensitive PII (BVN, credit card, password)
    await AuditLogger.record_async(
        session=session,
        action="IDENTITY_VERIFICATION_SUBMITTED",
        entity_type="person",
        entity_id=str(uuid.uuid4()),
        actor_role="customer",
        request_id="req-audit-test-777",
        details={
            "bvn": "22123456789",
            "password": "supersecretpassword",
            "card_number": "5399 1234 5678 9988",
            "phone": "08012345678",
        },
    )
    await session.commit()

    headers = make_auth_headers(Role.AUDITOR)

    # 1. Search without filters
    resp = await client.get("/api/v1/ops/audit-logs", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1

    # 2. Filter by request_id
    resp_filtered = await client.get("/api/v1/ops/audit-logs?request_id=req-audit-test-777", headers=headers)
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    assert filtered_data["total"] == 1

    item = filtered_data["items"][0]
    assert item["request_id"] == "req-audit-test-777"
    assert item["action"] == "IDENTITY_VERIFICATION_SUBMITTED"

    # Verify PII masking
    details = item["details"]
    assert details["password"] == "[REDACTED]"
    assert "12345678" not in details["bvn"]
    assert "9988" in details["card_number"]
    assert "****" in details["card_number"]


@pytest.mark.asyncio
async def test_phase_6_exit_check_request_diagnosis_by_id(client: AsyncClient, async_db):
    """PHASE 6 EXIT CHECK:
    An operator can identify a failing request by its Request ID and view the exact
    error trace and database events.
    """
    session, _ = async_db
    failing_req_id = "req-incident-fail-404-500"

    # 1. Simulate an audit event for the failing request
    await AuditLogger.record_async(
        session=session,
        action="REMOTE_GATEWAY_TIMEOUT_FAILED",
        entity_type="payment",
        entity_id="RRR-998877",
        actor_role="system",
        request_id=failing_req_id,
        details={"error_code": "ETIMEDOUT", "endpoint": "https://remita.gov.ng/api/v1"},
    )

    # 2. Simulate an AI run associated with this request
    ai_run = AIRun(
        request_id=failing_req_id,
        model_name="gpt-4o-mini",
        prompt_template_version="v1.0.0",
        intent="INFORMATIONAL",
        query_text="Did my payment go through?",
        answer_text="Under CMR law, automated agents cannot authoritatively verify payments.",
        retrieved_chunks=[],
        citations=[{"document_title": "CMR Operational Guidelines 2026"}],
        input_tokens=50,
        output_tokens=30,
        total_tokens=80,
        latency_ms=120.0,
        fallback_triggered=False,
        guardrail_triggered=True,
    )
    session.add(ai_run)
    await session.commit()

    # 3. Query diagnosis endpoint as Supervisor
    headers = make_auth_headers(Role.SUPERVISOR)
    resp = await client.get(f"/api/v1/ops/requests/{failing_req_id}", headers=headers)
    assert resp.status_code == 200
    diag = resp.json()

    assert diag["request_id"] == failing_req_id
    assert diag["events_count"] == 2
    assert diag["has_error_or_fallback"] is True
    assert diag["diagnosed_status"] == "FAILED_OR_DEGRADED"

    # Verify chronological timeline items
    timeline = diag["timeline"]
    sources = [t["source"] for t in timeline]
    assert "AUDIT_LOG" in sources
    assert "AI_INFERENCE_RUN" in sources

    # Check error details in audit item
    audit_item = next(t for t in timeline if t["source"] == "AUDIT_LOG")
    assert audit_item["details"]["error_code"] == "ETIMEDOUT"

    # Check AI item
    ai_item = next(t for t in timeline if t["source"] == "AI_INFERENCE_RUN")
    assert ai_item["guardrail_triggered"] is True


@pytest.mark.asyncio
async def test_incident_runbooks(client: AsyncClient):
    """Verify ops staff can retrieve standard operating procedure runbooks for alerts."""
    headers = make_auth_headers(Role.ADMIN)

    # 1. List all runbooks
    resp_list = await client.get("/api/v1/ops/runbooks", headers=headers)
    assert resp_list.status_code == 200
    runbooks = resp_list.json()
    assert len(runbooks) >= 4

    runbook_ids = [r["id"] for r in runbooks]
    assert "sustained_error_rate" in runbook_ids
    assert "high_ai_latency" in runbook_ids
    assert "ingestion_backlog" in runbook_ids
    assert "breached_case_sla" in runbook_ids

    # 2. Get specific runbook detail
    resp_detail = await client.get("/api/v1/ops/runbooks/sustained_error_rate", headers=headers)
    assert resp_detail.status_code == 200
    rb = resp_detail.json()

    assert rb["id"] == "sustained_error_rate"
    assert rb["severity"] == "CRITICAL"
    assert len(rb["diagnostic_steps"]) >= 3
    assert len(rb["mitigation_steps"]) >= 3
    assert "Lead Platform Engineer" in rb["escalation_role"]
