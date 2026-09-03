import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cases.commands import AssignCommand, RequestInfoCommand, TriageCommand
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


@pytest.mark.asyncio
async def test_customer_ask_informational_question(client: AsyncClient):
    """Customer asks a procedural question -> returns grounded answer with citations."""
    response = await client.post(
        "/api/v1/customer/questions",
        json={
            "question": "How do I obtain a motor vehicle clearance certificate in Lagos?",
            "channel": "web",
            "phone_number": "+2348011223344",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["intent"] == "INFORMATIONAL"
    assert "proof of vehicle ownership" in data["answer"].lower()
    assert len(data["citations"]) >= 1
    assert data["citations"][0]["document_title"] == "CMR Operational Guidelines 2026"
    assert data["prompt_case_creation"] is False
    assert data["conversation_id"] is not None

    # State extraction check
    facts = data["extracted_facts"]
    state_facts = [f for f in facts if f["fact_key"] == "registration_state"]
    assert len(state_facts) == 1
    assert state_facts[0]["fact_value"] == "Lagos"


@pytest.mark.asyncio
async def test_customer_ask_support_question_prompts_case(client: AsyncClient):
    """Customer asks an urgent/stolen vehicle question -> executes binary routing to SUPPORT_REQUEST."""
    response = await client.post(
        "/api/v1/customer/questions",
        json={
            "question": "Help me! My car was stolen yesterday in Abuja, VIN is 1HGCR2F83HA123456, plate KJA123AA!",
            "channel": "web",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["intent"] == "SUPPORT_REQUEST"
    assert data["prompt_case_creation"] is True
    assert data["suggested_category"] == "STOLEN_VEHICLE_REPORT"
    assert "Stolen" in data["suggested_subject"]

    # Verify extracted facts from message
    facts = {f["fact_key"]: f["fact_value"] for f in data["extracted_facts"]}
    assert "vin_or_chassis" in facts
    assert facts["vin_or_chassis"] == "1HGCR2F83HA123456"
    assert "license_plate" in facts
    assert facts["license_plate"] == "KJA123AA"
    assert "registration_state" in facts
    assert facts["registration_state"] == "Abuja"


@pytest.mark.asyncio
async def test_customer_open_case_prepopulates_facts(client: AsyncClient, async_db):
    """Opening a case with conversation_id pre-populates facts from chat history without re-typing."""
    session, _ = async_db

    # Step 1: Ingest question that yields facts
    q_resp = await client.post(
        "/api/v1/customer/questions",
        json={
            "question": "My vehicle clearance failed in Kano, chassis: 1HGCR2F83HA999999, plate KAN456XY",
            "phone_number": "+2348099887766",
        },
    )
    assert q_resp.status_code == 200
    conv_id = q_resp.json()["conversation_id"]

    # Step 2: Open case passing conversation_id
    case_resp = await client.post(
        "/api/v1/customer/cases",
        json={
            "subject": "Clearance Verification Error in Kano",
            "description": "System says clearance failed at inspection desk",
            "category": "CLEARANCE_FAILURE",
            "priority": "HIGH",
            "conversation_id": conv_id,
            "phone_number": "+2348099887766",
        },
    )
    assert case_resp.status_code == 201
    case_data = case_resp.json()

    assert case_data["case_number"].startswith("CMR-")
    assert case_data["status"] == "NEW"
    assert case_data["category"] == "CLEARANCE_FAILURE"
    assert case_data["priority"] == "HIGH"

    # Verify extracted facts transferred without re-typing
    facts = {f["fact_key"]: f["fact_value"] for f in case_data["extracted_facts"]}
    assert facts.get("vin_or_chassis") == "1HGCR2F83HA999999"
    assert facts.get("license_plate") == "KAN456XY"
    assert facts.get("registration_state") == "Kano"


@pytest.mark.asyncio
async def test_customer_get_case_timeline_and_requested_actions(client: AsyncClient, async_db):
    """Customer can view chronological timeline and explicit requested actions when case is WAITING."""
    session, _ = async_db

    # Create Person and Case directly
    person = await CaseService.create_person(
        session=session,
        full_name="Fatima Aliyu",
        phone_number="+2348022334455",
        email="fatima@example.ng",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Plate Number Replacement",
        category="PLATE_REPLACEMENT",
        priority=CasePriority.NORMAL,
    )
    await session.commit()

    # Move case: NEW -> TRIAGED -> IN_REVIEW -> WAITING (RequestInfo)
    await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=TriageCommand(category="PLATE_REPLACEMENT", priority=CasePriority.NORMAL, reason="Triage plate request"),
        actor_id=uuid.uuid4(),
        actor_role="support",
    )
    await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=AssignCommand(assignee_id=uuid.uuid4(), reason="Assign to officer"),
        actor_id=uuid.uuid4(),
        actor_role="support",
    )
    await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=RequestInfoCommand(
            requested_items=["Police Extract and Court Affidavit for lost plate"],
            reason="Official police report required for lost plate reissue",
        ),
        actor_id=uuid.uuid4(),
        actor_role="support",
    )
    await session.commit()

    # Fetch case detail as customer
    response = await client.get(f"/api/v1/customer/cases/{case.id}")
    assert response.status_code == 200
    detail = response.json()

    assert detail["status"] == "WAITING"
    assert len(detail["requested_actions"]) == 1
    action = detail["requested_actions"][0]
    assert "Police Extract and Court Affidavit" in str(action["requested_fields"])
    assert "Official police report required" in action["reason"]

    # Verify timeline items
    assert len(detail["timeline"]) >= 4
    event_types = [t["event_type"] for t in detail["timeline"]]
    assert "CASE_CREATED" in event_types
    assert "STATE_TRANSITION" in event_types


@pytest.mark.asyncio
async def test_customer_reply_automatically_shifts_waiting_to_in_review(client: AsyncClient, async_db):
    """Customer replying to a case in WAITING automatically shifts it to IN_REVIEW."""
    session, _ = async_db

    # Create Person and Case in WAITING status
    person = await CaseService.create_person(
        session=session,
        full_name="Babatunde Adeleke",
        phone_number="+2348033445566",
        email="babatunde@example.ng",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Ownership Transfer Verification",
        category="CHANGE_OF_OWNERSHIP",
    )
    await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=TriageCommand(category="CHANGE_OF_OWNERSHIP", reason="Triage transfer request"),
        actor_id=uuid.uuid4(),
        actor_role="support",
    )
    await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=AssignCommand(assignee_id=uuid.uuid4(), reason="Assign to officer"),
        actor_id=uuid.uuid4(),
        actor_role="support",
    )
    await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=RequestInfoCommand(requested_items=["Signed Deed of Sale"], reason="Need signed deed of sale"),
        actor_id=uuid.uuid4(),
        actor_role="support",
    )
    await session.commit()

    # Verify case is WAITING
    c_waiting = await CaseService.get_case_by_id(session, case.id)
    assert c_waiting.status == CaseStatus.WAITING

    # Customer replies via API
    reply_resp = await client.post(
        f"/api/v1/customer/cases/{case.id}/messages",
        json={
            "content": "I have uploaded the signed Deed of Sale and receipt from the previous owner.",
            "attachments": [{"filename": "deed_of_sale.pdf", "url": "https://storage/deed.pdf"}],
        },
    )
    assert reply_resp.status_code == 201
    reply_data = reply_resp.json()

    assert reply_data["status_shifted_to_in_review"] is True
    assert reply_data["case_status"] == "IN_REVIEW"

    # Verify in DB that status is now IN_REVIEW
    c_updated = await CaseService.get_case_by_id(session, case.id, include_events=True)
    assert c_updated.status == CaseStatus.IN_REVIEW

    # Verify timeline includes CustomerReply transition event
    last_event = c_updated.events[-1]
    assert last_event.command_name == "CustomerReply"
    assert last_event.from_status == "WAITING"
    assert last_event.to_status == "IN_REVIEW"
    assert last_event.actor_role == "customer"


@pytest.mark.asyncio
async def test_customer_isolation_and_security(client: AsyncClient, async_db):
    """Customer A cannot view or post replies to Customer B's case."""
    session, _ = async_db

    # Customer A
    person_a = await CaseService.create_person(
        session=session,
        full_name="Customer A",
        phone_number="+2348011111111",
        email="a@example.ng",
    )
    case_a = await CaseService.create_case(
        session=session,
        person_id=person_a.id,
        subject="Case belonging to Customer A",
    )
    await session.commit()

    token_a = create_access_token(subject=person_a.id, role=Role.CUSTOMER, email="a@example.ng")

    # Customer B
    person_b = await CaseService.create_person(
        session=session,
        full_name="Customer B",
        phone_number="+2348022222222",
        email="b@example.ng",
    )
    await session.commit()

    token_b = create_access_token(subject=person_b.id, role=Role.CUSTOMER, email="b@example.ng")

    # 1. Customer A can access Case A
    res_a = await client.get(
        f"/api/v1/customer/cases/{case_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 200

    # 2. Customer B is forbidden from accessing Case A
    res_b = await client.get(
        f"/api/v1/customer/cases/{case_a.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 403

    # 3. Customer B is forbidden from replying to Case A
    res_b_reply = await client.post(
        f"/api/v1/customer/cases/{case_a.id}/messages",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"content": "Malicious attempt to reply to Customer A's case"},
    )
    assert res_b_reply.status_code == 403
