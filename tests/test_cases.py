import uuid
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.cases.commands import (
    AssignCommand,
    CloseCommand,
    CustomerReplyCommand,
    ReopenCommand,
    RequestInfoCommand,
    ResolveCommand,
    TriageCommand,
)
from app.cases.models import (
    Case,
    CaseEvent,
    CasePriority,
    CaseStatus,
    Conversation,
    ExtractedFact,
    Message,
    Person,
)
from app.cases.service import CaseService
from app.cases.state_machine import (
    CaseStateMachine,
    IllegalStateTransitionError,
    UnauthorizedCommandError,
)
from app.platform.database import Base


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


@pytest.mark.asyncio
async def test_person_and_case_creation(async_db):
    session, _ = async_db

    person = await CaseService.create_person(
        session=session,
        full_name="Emeka Okafor",
        phone_number="+2348012345678",
        email="emeka@example.ng",
        nin_or_bvn="22334455667",
        contact_preferences={"channel": "whatsapp"},
        metadata_json={"state": "Lagos"},
    )
    await session.commit()

    assert person.id is not None
    assert person.full_name == "Emeka Okafor"
    assert person.created_at is not None

    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Vehicle Clearance Status",
        description="Assistance needed with Lagos CMR registration verification",
        category="MOTOR_CLEARANCE",
        priority=CasePriority.NORMAL,
        actor_role="customer",
    )
    await session.commit()

    assert case.id is not None
    assert case.case_number.startswith("CMR-")
    assert case.status == CaseStatus.NEW
    assert case.person_id == person.id

    # Verify initial creation event
    case_with_events = await CaseService.get_case_by_id(session, case.id, include_events=True)
    assert len(case_with_events.events) == 1
    event = case_with_events.events[0]
    assert event.event_type == "CASE_CREATED"
    assert event.to_status == "NEW"
    assert event.actor_role == "customer"


@pytest.mark.asyncio
async def test_complete_strict_case_lifecycle(async_db):
    """Verifies: NEW -> TRIAGED -> IN_REVIEW -> WAITING <-> IN_REVIEW -> RESOLVED -> CLOSED."""
    session, _ = async_db

    person = await CaseService.create_person(
        session=session,
        full_name="Fatima Bello",
        phone_number="+2348098765432",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Change of Ownership Request",
        actor_role="customer",
    )
    await session.commit()
    assert case.status == CaseStatus.NEW

    support_agent_id = uuid.uuid4()

    # 1. Triage: NEW -> TRIAGED
    triage_cmd = TriageCommand(
        category="CHANGE_OF_OWNERSHIP",
        priority=CasePriority.HIGH,
        reason="Ownership transfer verified for urgent processing",
    )
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=triage_cmd,
        actor_id=support_agent_id,
        actor_role="support",
    )
    await session.commit()
    assert case.status == CaseStatus.TRIAGED
    assert case.category == "CHANGE_OF_OWNERSHIP"
    assert case.priority == CasePriority.HIGH
    assert event.from_status == "NEW"
    assert event.to_status == "TRIAGED"
    assert event.command_name == "Triage"

    # 2. Assign: TRIAGED -> IN_REVIEW
    assignee_id = uuid.uuid4()
    assign_cmd = AssignCommand(
        assignee_id=assignee_id,
        reason="Assigning to Lagos zonal specialist",
    )
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=assign_cmd,
        actor_id=support_agent_id,
        actor_role="supervisor",
    )
    await session.commit()
    assert case.status == CaseStatus.IN_REVIEW
    assert case.assigned_to == assignee_id
    assert event.to_status == "IN_REVIEW"

    # 3. RequestInfo: IN_REVIEW -> WAITING
    req_cmd = RequestInfoCommand(
        requested_items=["Customs Single Goods Declaration", "Allocation Paper"],
        reason="Need clearer scan of customs duty document",
    )
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=req_cmd,
        actor_id=assignee_id,
        actor_role="support",
    )
    await session.commit()
    assert case.status == CaseStatus.WAITING
    assert event.to_status == "WAITING"

    # 4. CustomerReply: WAITING -> IN_REVIEW
    reply_cmd = CustomerReplyCommand(
        reply_text="Uploaded new high-res PDF of customs declaration",
        reason="Customer uploaded requested documents",
    )
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=reply_cmd,
        actor_id=person.id,
        actor_role="customer",
    )
    await session.commit()
    assert case.status == CaseStatus.IN_REVIEW
    assert event.to_status == "IN_REVIEW"

    # 5. Resolve: IN_REVIEW -> RESOLVED
    resolve_cmd = ResolveCommand(
        resolution_summary="Customs document verified. Police clearance issued.",
        reason="All documents validated against CMR central repository",
    )
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=resolve_cmd,
        actor_id=assignee_id,
        actor_role="support",
    )
    await session.commit()
    assert case.status == CaseStatus.RESOLVED
    assert case.resolved_at is not None
    assert event.to_status == "RESOLVED"

    # 6. Close: RESOLVED -> CLOSED
    close_cmd = CloseCommand(
        reason="Case archived after 48hr customer inactivity post-resolution",
    )
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=close_cmd,
        actor_id=None,
        actor_role="system",
    )
    await session.commit()
    assert case.status == CaseStatus.CLOSED
    assert case.closed_at is not None
    assert event.to_status == "CLOSED"


@pytest.mark.asyncio
async def test_reopen_from_resolved_and_closed(async_db):
    """Verifies that Reopening RESOLVED or CLOSED cases creates a new event and returns to IN_REVIEW."""
    session, _ = async_db

    person = await CaseService.create_person(
        session=session,
        full_name="Amina Yusuf",
        phone_number="+2348033333333",
    )
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject="Reopen test",
        actor_role="customer",
    )
    # Move NEW -> TRIAGED -> IN_REVIEW -> RESOLVED
    await CaseService.apply_command(
        session, case.id, TriageCommand(category="GENERAL_INQUIRY", reason="Triaged"), uuid.uuid4(), "support"
    )
    await CaseService.apply_command(
        session, case.id, AssignCommand(assignee_id=uuid.uuid4(), reason="Assigned"), uuid.uuid4(), "support"
    )
    await CaseService.apply_command(
        session, case.id, ResolveCommand(resolution_summary="Resolved initial issue", reason="Done"), uuid.uuid4(), "support"
    )
    await session.commit()
    assert case.status == CaseStatus.RESOLVED

    # Reopen from RESOLVED
    reopen_cmd = ReopenCommand(reason="Customer reported new discrepancy with engine number")
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=reopen_cmd,
        actor_id=person.id,
        actor_role="customer",
    )
    await session.commit()
    assert case.status == CaseStatus.IN_REVIEW
    assert event.command_name == "Reopen"
    assert event.from_status == "RESOLVED"
    assert event.to_status == "IN_REVIEW"

    # Resolve and Close again
    await CaseService.apply_command(
        session, case.id, ResolveCommand(resolution_summary="Engine verified", reason="Re-resolved"), uuid.uuid4(), "support"
    )
    await CaseService.apply_command(
        session, case.id, CloseCommand(reason="Final close"), uuid.uuid4(), "support"
    )
    await session.commit()
    assert case.status == CaseStatus.CLOSED

    # Reopen from CLOSED
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case.id,
        command=ReopenCommand(reason="Audit inspection requested re-check"),
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )
    await session.commit()
    assert case.status == CaseStatus.IN_REVIEW
    assert event.from_status == "CLOSED"
    assert event.to_status == "IN_REVIEW"


@pytest.mark.asyncio
async def test_illegal_transitions_raise_422(async_db):
    """Verifies that illegal transitions raise HTTP 422 with structured details."""
    session, _ = async_db

    person = await CaseService.create_person(session, "Test User", "+2348000000000")
    case = await CaseService.create_case(session, person.id, "Illegal transition test")
    await session.commit()
    assert case.status == CaseStatus.NEW

    # Attempt Resolve directly on NEW -> Must raise HTTP 422
    with pytest.raises(HTTPException) as exc_info:
        await CaseService.apply_command(
            session=session,
            case_id=case.id,
            command=ResolveCommand(resolution_summary="premature resolve", reason="invalid"),
            actor_id=uuid.uuid4(),
            actor_role="support",
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["error"] == "ILLEGAL_STATE_TRANSITION"
    assert detail["current_status"] == "NEW"
    assert detail["attempted_command"] == "Resolve"
    assert "Triage" in detail["allowed_commands"]

    # Attempt CustomerReply on NEW -> Must raise HTTP 422
    with pytest.raises(HTTPException) as exc_info:
        await CaseService.apply_command(
            session=session,
            case_id=case.id,
            command=CustomerReplyCommand(reply_text="hello"),
            actor_id=person.id,
            actor_role="customer",
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_unauthorized_role_raises_403(async_db):
    """Verifies that unauthorized actor roles cannot execute restricted commands."""
    session, _ = async_db

    person = await CaseService.create_person(session, "Customer User", "+2348111111111")
    case = await CaseService.create_case(session, person.id, "Role auth test")
    await session.commit()

    # Customer attempting to Triage case -> Must raise HTTP 403
    with pytest.raises(HTTPException) as exc_info:
        await CaseService.apply_command(
            session=session,
            case_id=case.id,
            command=TriageCommand(category="MOTOR_CLEARANCE", reason="Customer self-triaging"),
            actor_id=person.id,
            actor_role="customer",
        )
    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert detail["error"] == "UNAUTHORIZED_COMMAND"
    assert detail["actor_role"] == "customer"
    assert "support" in detail["allowed_roles"]


@pytest.mark.asyncio
async def test_extracted_facts_and_conversation_hierarchy(async_db):
    """Verifies ExtractedFact and Conversation/Message storage and linkages."""
    session, _ = async_db

    person = await CaseService.create_person(session, "Babajide Cole", "+2348022223344")
    case = await CaseService.create_case(session, person.id, "Fact extraction test")
    conv = await CaseService.create_conversation(session, person.id, case_id=case.id, channel="web")
    msg = await CaseService.add_message(
        session=session,
        conversation_id=conv.id,
        content="Vehicle VIN is 1HGCR2F83HA123456 and plate is LAGOS APP-421-XY",
        citations=[{"doc": "CMR Guidelines", "chunk": 5}],
        intent="SUPPORT_REQUEST",
    )

    fact_vin = await CaseService.add_extracted_fact(
        session=session,
        case_id=case.id,
        fact_key="vin",
        fact_value="1HGCR2F83HA123456",
        confidence=0.98,
        source="AI_EXTRACTION",
        verified=False,
        conversation_id=conv.id,
        message_id=msg.id,
    )
    fact_plate = await CaseService.add_extracted_fact(
        session=session,
        case_id=case.id,
        fact_key="plate_number",
        fact_value="APP-421-XY",
        confidence=0.99,
        source="AI_EXTRACTION",
        verified=True,
    )
    await session.commit()

    # Query back case with facts
    case_with_facts = await CaseService.get_case_by_id(session, case.id, include_facts=True)
    assert len(case_with_facts.extracted_facts) == 2
    keys = {f.fact_key: f.fact_value for f in case_with_facts.extracted_facts}
    assert keys["vin"] == "1HGCR2F83HA123456"
    assert keys["plate_number"] == "APP-421-XY"


@pytest.mark.asyncio
async def test_phase_1_exit_check_persistence_across_restart(tmp_path):
    """PHASE 1 EXIT CHECK:
    Case survives database restart with an intact chronological timeline.
    Simulates database restart by:
    1. Creating person, case, executing lifecycle commands on Engine 1.
    2. Completely disposing Engine 1 and session.
    3. Initializing Engine 2 on the same disk database.
    4. Querying and validating full timeline, timestamps, commands, and case state.
    """
    db_file = tmp_path / "cmr_persistent_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # --- SESSION 1: Create Case & Execute Commands ---
    engine1 = create_async_engine(db_url, echo=False)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker1 = async_sessionmaker(engine1, class_=AsyncSession, expire_on_commit=False)

    async with session_maker1() as session1:
        person = await CaseService.create_person(session1, "Danjuma Musa", "+2348055555555")
        case = await CaseService.create_case(
            session1,
            person_id=person.id,
            subject="Persistent Case Survives Restart",
            category="CMR_REGISTRATION",
            priority=CasePriority.NORMAL,
            actor_role="customer",
        )
        case_id = case.id
        person_id = person.id
        agent_id = uuid.uuid4()

        # Command 1: Triage
        await CaseService.apply_command(
            session1,
            case_id,
            TriageCommand(category="CMR_REGISTRATION", priority=CasePriority.URGENT, reason="Priority vehicle clearance"),
            actor_id=agent_id,
            actor_role="support",
        )

        # Command 2: Assign
        specialist_id = uuid.uuid4()
        await CaseService.apply_command(
            session1,
            case_id,
            AssignCommand(assignee_id=specialist_id, reason="Assigned to senior officer"),
            actor_id=agent_id,
            actor_role="supervisor",
        )

        # Command 3: RequestInfo
        await CaseService.apply_command(
            session1,
            case_id,
            RequestInfoCommand(requested_items=["NIN Slip", "Proof of ownership"], reason="Awaiting verified identity"),
            actor_id=specialist_id,
            actor_role="support",
        )

        # Command 4: CustomerReply
        await CaseService.apply_command(
            session1,
            case_id,
            CustomerReplyCommand(reply_text="Attached NIN slip and invoice"),
            actor_id=person_id,
            actor_role="customer",
        )

        # Command 5: Resolve
        await CaseService.apply_command(
            session1,
            case_id,
            ResolveCommand(resolution_summary="Registration approved and stamped", reason="All criteria satisfied"),
            actor_id=specialist_id,
            actor_role="support",
        )

        await session1.commit()

    # --- SIMULATE RESTART: Disconnect and kill engine 1 ---
    await engine1.dispose()

    # --- SESSION 2: Reconnect to the database after 'restart' ---
    engine2 = create_async_engine(db_url, echo=False)
    session_maker2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)

    async with session_maker2() as session2:
        reloaded_case = await CaseService.get_case_by_id(session2, case_id, include_events=True)

        # 1. Verify Case attributes survived intact
        assert reloaded_case is not None
        assert reloaded_case.id == case_id
        assert reloaded_case.person_id == person_id
        assert reloaded_case.status == CaseStatus.RESOLVED
        assert reloaded_case.priority == CasePriority.URGENT
        assert reloaded_case.category == "CMR_REGISTRATION"
        assert reloaded_case.resolved_at is not None

        # 2. Verify complete chronological CaseEvent timeline survived intact
        timeline = reloaded_case.events
        assert len(timeline) == 6  # 1 creation + 5 transition events

        # Event 0: CASE_CREATED
        assert timeline[0].event_type == "CASE_CREATED"
        assert timeline[0].to_status == "NEW"
        assert timeline[0].actor_role == "customer"

        # Event 1: Triage
        assert timeline[1].command_name == "Triage"
        assert timeline[1].from_status == "NEW"
        assert timeline[1].to_status == "TRIAGED"
        assert timeline[1].actor_role == "support"
        assert "Priority vehicle clearance" in timeline[1].reason

        # Event 2: Assign
        assert timeline[2].command_name == "Assign"
        assert timeline[2].from_status == "TRIAGED"
        assert timeline[2].to_status == "IN_REVIEW"
        assert timeline[2].actor_role == "supervisor"

        # Event 3: RequestInfo
        assert timeline[3].command_name == "RequestInfo"
        assert timeline[3].from_status == "IN_REVIEW"
        assert timeline[3].to_status == "WAITING"
        assert timeline[3].payload["requested_items"] == ["NIN Slip", "Proof of ownership"]

        # Event 4: CustomerReply
        assert timeline[4].command_name == "CustomerReply"
        assert timeline[4].from_status == "WAITING"
        assert timeline[4].to_status == "IN_REVIEW"
        assert timeline[4].actor_role == "customer"

        # Event 5: Resolve
        assert timeline[5].command_name == "Resolve"
        assert timeline[5].from_status == "IN_REVIEW"
        assert timeline[5].to_status == "RESOLVED"
        assert timeline[5].actor_role == "support"
        assert "Registration approved and stamped" in timeline[5].payload["resolution_summary"]

        # 3. Verify strict chronological ordering of timestamps
        for i in range(len(timeline) - 1):
            assert timeline[i].created_at <= timeline[i + 1].created_at

    await engine2.dispose()
