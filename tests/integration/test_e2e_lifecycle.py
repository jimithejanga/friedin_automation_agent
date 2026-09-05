import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cases.models import CasePriority, CaseStatus
from app.main import create_app
from app.platform.auth import Role, create_access_token
from app.platform.database import Base, get_db_session
from scripts.seed_db import seed_procedural_knowledge, seed_staff_accounts


@pytest.fixture
async def async_db():
    """Provides an isolated database seeded with procedural knowledge and staff accounts."""
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
        await seed_staff_accounts(session)
        await seed_procedural_knowledge(session)
        await session.commit()
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


def make_token(role: Role, user_id: uuid.UUID | None = None) -> dict:
    sub = str(user_id or uuid.uuid4())
    token = create_access_token(
        subject=sub,
        email=f"{role.value}@cmr.police.gov.ng",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_full_end_to_end_lifecycle(client: AsyncClient):
    """Complete E2E test verifying the full lifecycle specified in Phase 7:
    Question -> Case Created -> Triaged -> In Review -> Resolved -> Closed.
    """
    support_headers = make_token(Role.SUPPORT)
    supervisor_headers = make_token(Role.SUPERVISOR)

    # -------------------------------------------------------------------------
    # STEP 1: Customer asks question with vehicle facts
    # -------------------------------------------------------------------------
    question_payload = {
        "question": "Help me! My car was stolen yesterday in Lagos. VIN: 1HGCR2F83HA998877, plate: KJA123AA, phone: 08011223344",
        "channel": "web",
        "phone_number": "08011223344",
        "full_name": "Babatunde Adeleke",
    }
    q_resp = await client.post("/api/v1/customer/questions", json=question_payload)
    assert q_resp.status_code == 200
    q_data = q_resp.json()

    assert q_data["intent"] == "SUPPORT_REQUEST"
    assert q_data["prompt_case_creation"] is True
    assert q_data["suggested_category"] == "STOLEN_VEHICLE_REPORT"
    conversation_id = q_data["conversation_id"]
    assert conversation_id is not None

    extracted_facts = {f["fact_key"]: f["fact_value"] for f in q_data["extracted_facts"]}
    assert extracted_facts.get("vin_or_chassis") == "1HGCR2F83HA998877"
    assert extracted_facts.get("license_plate") == "KJA123AA"
    assert extracted_facts.get("registration_state") == "Lagos"

    # -------------------------------------------------------------------------
    # STEP 2: Customer opens case pre-populated from chat history
    # -------------------------------------------------------------------------
    case_payload = {
        "subject": "Report of Stolen Honda Accord in Lagos",
        "description": "Vehicle was stolen from office premises. Please flag on national CMR registry.",
        "category": q_data["suggested_category"],
        "priority": "URGENT",
        "conversation_id": conversation_id,
        "full_name": "Babatunde Adeleke",
        "phone_number": "08011223344",
        "email": "babatunde@example.com",
    }
    open_resp = await client.post("/api/v1/customer/cases", json=case_payload)
    assert open_resp.status_code == 201
    case_data = open_resp.json()

    case_id = case_data["id"]
    case_number = case_data["case_number"]
    assert case_data["status"] == "NEW"
    assert case_data["priority"] == "URGENT"
    assert len(case_data["extracted_facts"]) >= 3

    # -------------------------------------------------------------------------
    # STEP 3: Support Desk finds the case in queue & triages it
    # -------------------------------------------------------------------------
    queue_resp = await client.get("/api/v1/support/cases?status=NEW&priority=URGENT", headers=support_headers)
    assert queue_resp.status_code == 200
    queue_data = queue_resp.json()
    assert any(c["id"] == case_id for c in queue_data["cases"])

    triage_payload = {
        "category": "STOLEN_VEHICLE_REPORT",
        "priority": "URGENT",
        "reason": "Verified initial customer report and vehicle chassis details",
    }
    triage_resp = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/triage",
        json=triage_payload,
        headers=support_headers,
    )
    assert triage_resp.status_code == 200
    assert triage_resp.json()["to_status"] == "TRIAGED"

    # -------------------------------------------------------------------------
    # STEP 4: Support Supervisor assigns case
    # -------------------------------------------------------------------------
    agent_id = str(uuid.uuid4())
    assign_payload = {
        "assignee_id": agent_id,
        "reason": "Assigned to Lagos command stolen vehicle unit",
    }
    assign_resp = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/assign",
        json=assign_payload,
        headers=supervisor_headers,
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["payload"]["assignee_id"] == agent_id

    # Verify assignment via Support Case Detail
    support_detail_resp = await client.get(f"/api/v1/support/cases/{case_id}", headers=support_headers)
    assert support_detail_resp.status_code == 200
    assert support_detail_resp.json()["assigned_to"] == agent_id

    # -------------------------------------------------------------------------
    # STEP 5: Support Desk requests additional information (shifts to WAITING)
    # -------------------------------------------------------------------------
    request_info_payload = {
        "requested_items": ["police_fir_document"],
        "reason": "Please upload police incident FIR report from Lagos Command",
    }
    req_info_resp = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/request_info",
        json=request_info_payload,
        headers=support_headers,
    )
    assert req_info_resp.status_code == 200
    assert req_info_resp.json()["to_status"] == "WAITING"

    # Verify customer sees requested actions while WAITING
    cust_waiting_resp = await client.get(f"/api/v1/customer/cases/{case_id}")
    assert cust_waiting_resp.status_code == 200
    cust_waiting_data = cust_waiting_resp.json()
    assert len(cust_waiting_data["requested_actions"]) >= 1
    assert cust_waiting_data["requested_actions"][0]["requested_fields"] == ["police_fir_document"]

    # -------------------------------------------------------------------------
    # STEP 6: Customer submits requested info (automatically shifts to IN_REVIEW)
    # -------------------------------------------------------------------------
    customer_reply_payload = {
        "content": "Here is the police FIR report: Station Ikeja, FIR No: LAG/IKJ/2026/04412. All details verified.",
    }
    reply_resp = await client.post(
        f"/api/v1/customer/cases/{case_id}/messages",
        json=customer_reply_payload,
    )
    assert reply_resp.status_code == 201
    reply_data = reply_resp.json()
    assert reply_data["case_status"] == "IN_REVIEW"
    assert reply_data["status_shifted_to_in_review"] is True

    # -------------------------------------------------------------------------
    # STEP 7: Staff adds confidential internal note
    # -------------------------------------------------------------------------
    note_payload = {
        "note": "Cross-checked with Ikeja station DPO. FIR No. confirmed authentic. Flagged vehicle nationwide.",
    }
    note_resp = await client.post(
        f"/api/v1/support/cases/{case_id}/notes",
        json=note_payload,
        headers=support_headers,
    )
    assert note_resp.status_code == 201

    # -------------------------------------------------------------------------
    # STEP 8: Support resolves case (IN_REVIEW -> RESOLVED)
    # -------------------------------------------------------------------------
    resolve_payload = {
        "resolution_summary": "Vehicle successfully blacklisted and alerted across all 36 state border commands.",
        "reason": "All clearance blocks instituted.",
    }
    resolve_resp = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/resolve",
        json=resolve_payload,
        headers=support_headers,
    )
    assert resolve_resp.status_code == 200
    resolved_data = resolve_resp.json()
    assert resolved_data["to_status"] == "RESOLVED"

    # -------------------------------------------------------------------------
    # STEP 9: Supervisor closes case (RESOLVED -> CLOSED)
    # -------------------------------------------------------------------------
    close_payload = {
        "reason": "Case completed and validated under CMR investigative protocol.",
    }
    close_resp = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/close",
        json=close_payload,
        headers=supervisor_headers,
    )
    assert close_resp.status_code == 200
    closed_data = close_resp.json()
    assert closed_data["to_status"] == "CLOSED"

    # -------------------------------------------------------------------------
    # STEP 10: Customer views case timeline - verifies intact chronological audit
    # -------------------------------------------------------------------------
    detail_resp = await client.get(f"/api/v1/customer/cases/{case_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert detail["case_number"] == case_number
    assert detail["status"] == "CLOSED"
    timeline = detail["timeline"]

    event_types = [t["event_type"] for t in timeline]
    assert "CASE_CREATED" in event_types
    assert "STATE_TRANSITION" in event_types

    to_statuses = [t.get("to_status") for t in timeline if t.get("to_status")]
    assert "TRIAGED" in to_statuses
    assert "WAITING" in to_statuses
    assert "IN_REVIEW" in to_statuses
    assert "RESOLVED" in to_statuses
    assert "CLOSED" in to_statuses
