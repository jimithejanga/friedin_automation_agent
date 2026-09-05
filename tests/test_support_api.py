import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cases.models import CasePriority, CaseStatus
from app.cases.service import CaseService
from app.main import create_app
from app.platform.auth import Role, create_access_token
from app.platform.database import Base, get_db_session


@pytest.fixture
async def async_db():
    """Provides an isolated in-memory SQLite database for testing."""
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


@pytest.fixture
def support_headers():
    staff_id = uuid.uuid4()
    token = create_access_token(subject=staff_id, role=Role.SUPPORT, email="agent@police.gov.ng")
    return {"Authorization": f"Bearer {token}"}, staff_id


@pytest.fixture
def supervisor_headers():
    sup_id = uuid.uuid4()
    token = create_access_token(subject=sup_id, role=Role.SUPERVISOR, email="supervisor@police.gov.ng")
    return {"Authorization": f"Bearer {token}"}, sup_id


@pytest.fixture
def customer_headers():
    cust_id = uuid.uuid4()
    token = create_access_token(subject=cust_id, role=Role.CUSTOMER, email="citizen@example.ng")
    return {"Authorization": f"Bearer {token}"}, cust_id


@pytest.mark.asyncio
async def test_support_rbac_enforcement(client: AsyncClient, support_headers, customer_headers):
    """Test that support console requires authentication and forbids customer role."""
    # 1. Unauthenticated request -> 401
    resp_unauth = await client.get("/api/v1/support/cases")
    assert resp_unauth.status_code == 401

    # 2. Customer role -> 403 Forbidden
    cust_h, _ = customer_headers
    resp_cust = await client.get("/api/v1/support/cases", headers=cust_h)
    assert resp_cust.status_code == 403

    # 3. Support role -> 200 OK
    supp_h, _ = support_headers
    resp_supp = await client.get("/api/v1/support/cases", headers=supp_h)
    assert resp_supp.status_code == 200


@pytest.mark.asyncio
async def test_people_cross_case_search(client: AsyncClient, async_db, support_headers):
    """Support agent can search people by name, phone, email, NIN and view all their cases."""
    session, _ = async_db
    supp_h, _ = support_headers

    # Person 1 with 2 cases
    p1 = await CaseService.create_person(
        session=session,
        full_name="Chukwudi Nnamdi",
        phone_number="+2348011112222",
        email="chukwudi@police.gov.ng",
        nin_or_bvn="12345678901",
    )
    c1 = await CaseService.create_case(
        session=session,
        person_id=p1.id,
        subject="Vehicle Clearance Delays in Abuja",
        category="MOTOR_CLEARANCE",
        priority=CasePriority.HIGH,
    )
    c2 = await CaseService.create_case(
        session=session,
        person_id=p1.id,
        subject="Change of Ownership Query",
        category="CHANGE_OF_OWNERSHIP",
        priority=CasePriority.NORMAL,
    )

    # Person 2 with 1 case
    p2 = await CaseService.create_person(
        session=session,
        full_name="Amina Bello",
        phone_number="+2348033334444",
        email="amina@example.ng",
        nin_or_bvn="98765432109",
    )
    c3 = await CaseService.create_case(
        session=session,
        person_id=p2.id,
        subject="Plate Number Reissue",
        category="PLATE_REPLACEMENT",
        priority=CasePriority.URGENT,
    )
    await session.commit()

    # 1. Search by name query "Chukwudi"
    res1 = await client.get("/api/v1/support/people?q=Chukwudi", headers=supp_h)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total"] == 1
    assert data1["people"][0]["full_name"] == "Chukwudi Nnamdi"
    assert data1["people"][0]["total_cases_count"] == 2
    assert len(data1["people"][0]["cases"]) == 2

    # 2. Search by NIN
    res2 = await client.get("/api/v1/support/people?nin_or_bvn=98765432109", headers=supp_h)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["total"] == 1
    assert data2["people"][0]["full_name"] == "Amina Bello"
    assert data2["people"][0]["total_cases_count"] == 1

    # 3. Search by phone number
    res3 = await client.get("/api/v1/support/people?phone_number=+2348011112222", headers=supp_h)
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["total"] == 1
    assert data3["people"][0]["full_name"] == "Chukwudi Nnamdi"


@pytest.mark.asyncio
async def test_case_queue_filtering(client: AsyncClient, async_db, support_headers):
    """Support agents can filter queues by status, priority, category, assignee, and SLA."""
    session, _ = async_db
    supp_h, staff_id = support_headers

    person = await CaseService.create_person(
        session=session,
        full_name="Queue Tester",
        phone_number="+2348099998888",
    )

    # Case 1: Urgent motor clearance assigned to staff_id, SLA breached
    past_sla = datetime.now(timezone.utc) - timedelta(hours=2)
    c1 = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Urgent Stolen Vehicle Notice",
        category="STOLEN_VEHICLE",
        priority=CasePriority.URGENT,
    )
    c1.assigned_to = staff_id
    c1.sla_deadline = past_sla

    # Case 2: Normal inquiry unassigned, SLA in future
    future_sla = datetime.now(timezone.utc) + timedelta(hours=24)
    c2 = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="General Fee Inquiries",
        category="GENERAL_INQUIRY",
        priority=CasePriority.NORMAL,
    )
    c2.sla_deadline = future_sla

    await session.commit()

    # Filter 1: By priority URGENT
    res_prio = await client.get("/api/v1/support/cases?priority=URGENT", headers=supp_h)
    assert res_prio.status_code == 200
    d_prio = res_prio.json()
    assert d_prio["total"] == 1
    assert d_prio["cases"][0]["subject"] == "Urgent Stolen Vehicle Notice"

    # Filter 2: By assigned_to
    res_assigned = await client.get(f"/api/v1/support/cases?assignee_id={staff_id}", headers=supp_h)
    assert res_assigned.status_code == 200
    d_assigned = res_assigned.json()
    assert d_assigned["total"] == 1
    assert d_assigned["cases"][0]["id"] == str(c1.id)

    # Filter 3: By unassigned
    res_unassigned = await client.get("/api/v1/support/cases?unassigned=true", headers=supp_h)
    assert res_unassigned.status_code == 200
    d_unassigned = res_unassigned.json()
    assert d_unassigned["total"] == 1
    assert d_unassigned["cases"][0]["id"] == str(c2.id)

    # Filter 4: By SLA breached
    res_breached = await client.get("/api/v1/support/cases?sla_breached=true", headers=supp_h)
    assert res_breached.status_code == 200
    d_breached = res_breached.json()
    assert d_breached["total"] == 1
    assert d_breached["cases"][0]["is_sla_breached"] is True
    assert d_breached["cases"][0]["id"] == str(c1.id)


@pytest.mark.asyncio
async def test_support_named_command_lifecycle(client: AsyncClient, async_db, support_headers):
    """Execute full case command lifecycle: Triage -> Assign -> RequestInfo -> Resolve -> Close -> Reopen."""
    session, _ = async_db
    supp_h, staff_id = support_headers

    person = await CaseService.create_person(
        session=session,
        full_name="Command Lifecycle Subject",
        phone_number="+2348077665544",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Plate Number Issuance",
    )
    await session.commit()
    case_id = str(case.id)

    # 1. Triage: NEW -> TRIAGED
    res_triage = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/triage",
        headers=supp_h,
        json={
            "category": "PLATE_REPLACEMENT",
            "priority": "HIGH",
            "reason": "Verified citizen identification papers",
        },
    )
    assert res_triage.status_code == 200
    data_triage = res_triage.json()
    assert data_triage["command_name"] == "Triage"
    assert data_triage["from_status"] == "NEW"
    assert data_triage["to_status"] == "TRIAGED"

    # 2. Assign: TRIAGED -> IN_REVIEW
    specialist_uuid = uuid.uuid4()
    res_assign = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/assign",
        headers=supp_h,
        json={
            "assignee_id": str(specialist_uuid),
            "reason": "Assigning to regional inspection lead",
        },
    )
    assert res_assign.status_code == 200
    data_assign = res_assign.json()
    assert data_assign["command_name"] == "Assign"
    assert data_assign["from_status"] == "TRIAGED"
    assert data_assign["to_status"] == "IN_REVIEW"

    # 3. RequestInfo: IN_REVIEW -> WAITING
    res_req = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/request-info",
        headers=supp_h,
        json={
            "requested_items": ["Police Extract", "Sworn Affidavit"],
            "reason": "Proof of lost plate required by standard regulation",
        },
    )
    assert res_req.status_code == 200
    data_req = res_req.json()
    assert data_req["command_name"] == "RequestInfo"
    assert data_req["from_status"] == "IN_REVIEW"
    assert data_req["to_status"] == "WAITING"

    # 4. Customer replies (simulated via customer message endpoint): WAITING -> IN_REVIEW
    res_reply = await client.post(
        f"/api/v1/customer/cases/{case_id}/messages",
        json={"content": "Here is my police extract number: EXT-998822"},
    )
    assert res_reply.status_code == 201
    assert res_reply.json()["case_status"] == "IN_REVIEW"

    # 5. Resolve: IN_REVIEW -> RESOLVED
    res_resolve = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/resolve",
        headers=supp_h,
        json={
            "resolution_summary": "Reissue clearance authorized and sent to state desk.",
            "reason": "Police extract verified against central repository.",
        },
    )
    assert res_resolve.status_code == 200
    data_resolve = res_resolve.json()
    assert data_resolve["command_name"] == "Resolve"
    assert data_resolve["from_status"] == "IN_REVIEW"
    assert data_resolve["to_status"] == "RESOLVED"

    # 6. Close: RESOLVED -> CLOSED
    res_close = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/close",
        headers=supp_h,
        json={"reason": "Citizen acknowledged receipt of replacement certificate."},
    )
    assert res_close.status_code == 200
    data_close = res_close.json()
    assert data_close["command_name"] == "Close"
    assert data_close["from_status"] == "RESOLVED"
    assert data_close["to_status"] == "CLOSED"

    # 7. Reopen: CLOSED -> IN_REVIEW
    res_reopen = await client.post(
        f"/api/v1/support/cases/{case_id}/commands/reopen",
        headers=supp_h,
        json={"reason": "Citizen reported plate printing typo on engine number."},
    )
    assert res_reopen.status_code == 200
    data_reopen = res_reopen.json()
    assert data_reopen["command_name"] == "Reopen"
    assert data_reopen["from_status"] == "CLOSED"
    assert data_reopen["to_status"] == "IN_REVIEW"


@pytest.mark.asyncio
async def test_support_illegal_transition_raises_422(client: AsyncClient, async_db, support_headers):
    """Attempting an illegal transition (e.g. Close on a NEW case) raises HTTP 422 with error details."""
    session, _ = async_db
    supp_h, _ = support_headers

    person = await CaseService.create_person(
        session=session,
        full_name="Invalid Transition Subject",
        phone_number="+2348011223344",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Brand New Case",
    )
    await session.commit()

    # Case is NEW. Attempting to Close directly must fail with 422
    res_illegal = await client.post(
        f"/api/v1/support/cases/{case.id}/commands/close",
        headers=supp_h,
        json={"reason": "Illegal direct close attempt"},
    )
    assert res_illegal.status_code == 422
    error_data = res_illegal.json()["detail"]
    assert error_data["error"] == "ILLEGAL_STATE_TRANSITION"
    assert error_data["current_status"] == "NEW"
    assert error_data["attempted_command"] == "Close"
    assert "Triage" in error_data["allowed_commands"]


@pytest.mark.asyncio
async def test_support_internal_notes_and_customer_confidentiality(
    client: AsyncClient, async_db, support_headers
):
    """Internal notes recorded by support staff are visible in Support Console but hidden from Customer view."""
    session, _ = async_db
    supp_h, staff_id = support_headers

    person = await CaseService.create_person(
        session=session,
        full_name="Secret Note Citizen",
        phone_number="+2348055443322",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Suspected Document Forgery",
    )
    await session.commit()
    case_id = str(case.id)

    # 1. Staff records an internal note and administrative decision
    note_text = "CONFIDENTIAL: NIN biometric mismatch flagged on state database."
    decision_text = "Refer to CID Anti-Fraud unit for background inspection."
    res_note = await client.post(
        f"/api/v1/support/cases/{case_id}/notes",
        headers=supp_h,
        json={
            "note": note_text,
            "decision": decision_text,
            "reason": "Routine biometric audit discrepancy",
        },
    )
    assert res_note.status_code == 201
    d_note = res_note.json()
    assert d_note["event_type"] == "INTERNAL_NOTE"
    assert d_note["note"] == note_text
    assert d_note["decision"] == decision_text

    # 2. Staff views case in Support Console -> Note IS present
    res_supp_view = await client.get(f"/api/v1/support/cases/{case_id}", headers=supp_h)
    assert res_supp_view.status_code == 200
    supp_timeline = res_supp_view.json()["timeline"]
    event_types = [t["event_type"] for t in supp_timeline]
    assert "INTERNAL_NOTE" in event_types

    # 3. Customer views case on Customer Surface -> Internal note is NOT present
    res_cust_view = await client.get(f"/api/v1/customer/cases/{case_id}")
    assert res_cust_view.status_code == 200
    cust_timeline = res_cust_view.json()["timeline"]
    cust_event_types = [t["event_type"] for t in cust_timeline]
    assert "INTERNAL_NOTE" not in cust_event_types
    for item in cust_timeline:
        assert "CONFIDENTIAL" not in item["description"]
