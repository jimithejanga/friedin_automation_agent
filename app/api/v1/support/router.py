import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.support.schemas import (
    AssignCommandPayload,
    CloseCommandPayload,
    CommandExecutionResponse,
    PersonCaseSummarySchema,
    PersonSearchResponse,
    PersonSummarySchema,
    RecordInternalNoteRequest,
    RecordInternalNoteResponse,
    ReopenCommandPayload,
    RequestInfoCommandPayload,
    ResolveCommandPayload,
    SupportCaseDetailResponse,
    SupportCaseListResponse,
    SupportCaseSummarySchema,
    SupportExtractedFactSchema,
    SupportMessageSchema,
    SupportTimelineItemSchema,
    TriageCommandPayload,
)
from app.cases.commands import (
    AssignCommand,
    BaseCaseCommand,
    CloseCommand,
    ReopenCommand,
    RequestInfoCommand,
    ResolveCommand,
    TriageCommand,
)
from app.cases.models import CasePriority, CaseStatus
from app.cases.service import CaseService
from app.platform.auth import AuthenticatedUser, Role, require_roles
from app.platform.database import get_db_session

router = APIRouter()

SUPPORT_ROLES = (Role.SUPPORT, Role.SUPERVISOR, Role.ADMIN)


@router.get(
    "/people",
    response_model=PersonSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Cross-case search by name, phone, email, or verified identity identifier",
)
async def search_people(
    q: Optional[str] = Query(None, description="General search query across name, phone, email, NIN/BVN"),
    phone_number: Optional[str] = Query(None, description="Filter by phone number"),
    email: Optional[str] = Query(None, description="Filter by email"),
    nin_or_bvn: Optional[str] = Query(None, description="Filter by NIN or BVN"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> PersonSearchResponse:
    """Search people across all cases with cross-case history summaries."""
    total, people = await CaseService.search_people(
        session=session,
        query=q,
        phone_number=phone_number,
        email=email,
        nin_or_bvn=nin_or_bvn,
        limit=limit,
        offset=offset,
    )

    summaries: List[PersonSummarySchema] = []
    for person in people:
        cases_list = sorted(person.cases, key=lambda c: c.created_at, reverse=True)
        total_cases = len(cases_list)
        open_cases = sum(
            1 for c in cases_list if c.status not in (CaseStatus.RESOLVED, CaseStatus.CLOSED)
        )
        case_items = [
            PersonCaseSummarySchema(
                id=c.id,
                case_number=c.case_number,
                status=c.status,
                priority=c.priority,
                category=c.category,
                subject=c.subject,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in cases_list
        ]
        summaries.append(
            PersonSummarySchema(
                id=person.id,
                full_name=person.full_name,
                phone_number=person.phone_number,
                email=person.email,
                nin_or_bvn=person.nin_or_bvn,
                total_cases_count=total_cases,
                open_cases_count=open_cases,
                cases=case_items,
            )
        )

    return PersonSearchResponse(total=total, people=summaries)


def is_deadline_breached(deadline: Optional[datetime], case_status: CaseStatus) -> bool:
    """Check if case deadline is breached safely handling both offset-naive and offset-aware datetimes."""
    if not deadline or case_status in (CaseStatus.RESOLVED, CaseStatus.CLOSED):
        return False
    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline < now


@router.get(
    "/cases",
    response_model=SupportCaseListResponse,
    status_code=status.HTTP_200_OK,
    summary="Queue filtering by status, priority, category, assignee, and SLA",
)
async def list_cases(
    status_filter: Optional[CaseStatus] = Query(None, alias="status", description="Filter by case status"),
    priority: Optional[CasePriority] = Query(None, description="Filter by case priority"),
    category: Optional[str] = Query(None, description="Filter by case category"),
    assignee_id: Optional[uuid.UUID] = Query(None, description="Filter by assigned staff UUID"),
    unassigned: bool = Query(False, description="Filter unassigned cases only"),
    sla_breached: Optional[bool] = Query(None, description="Filter by SLA breach status"),
    search: Optional[str] = Query(None, description="Search case number, subject or description"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> SupportCaseListResponse:
    """List and filter support cases with queue metrics and SLA breach status."""
    total, cases = await CaseService.filter_cases(
        session=session,
        status=status_filter,
        priority=priority,
        category=category,
        assignee_id=assignee_id,
        unassigned_only=unassigned,
        sla_breached=sla_breached,
        search=search,
        limit=limit,
        offset=offset,
    )

    summaries: List[SupportCaseSummarySchema] = []
    for c in cases:
        breached = is_deadline_breached(c.sla_deadline, c.status)
        summaries.append(
            SupportCaseSummarySchema(
                id=c.id,
                case_number=c.case_number,
                person_id=c.person_id,
                person_name=c.person.full_name if c.person else None,
                person_phone=c.person.phone_number if c.person else None,
                status=c.status,
                priority=c.priority,
                category=c.category,
                subject=c.subject,
                assigned_to=c.assigned_to,
                sla_deadline=c.sla_deadline,
                is_sla_breached=breached,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )

    return SupportCaseListResponse(total=total, cases=summaries)


@router.get(
    "/cases/{case_id}",
    response_model=SupportCaseDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Detailed support case view including internal notes, history, and SLA",
)
async def get_support_case_detail(
    case_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> SupportCaseDetailResponse:
    """Retrieve full support console case detail, including internal staff notes and decisions."""
    case = await CaseService.get_case_for_support(session=session, case_id=case_id)
    breached = is_deadline_breached(case.sla_deadline, case.status)

    # Timeline with all events (including INTERNAL_NOTE)
    timeline: List[SupportTimelineItemSchema] = []
    for event in case.events:
        desc = event.event_type
        if event.event_type == "CASE_CREATED":
            desc = "Case opened"
        elif event.event_type == "INTERNAL_NOTE":
            desc = f"Internal Note: {event.payload.get('note', '')[:60]}..." if len(event.payload.get('note', '')) > 60 else f"Internal Note: {event.payload.get('note', '')}"
        elif event.reason:
            desc = event.reason

        timeline.append(
            SupportTimelineItemSchema(
                id=event.id,
                event_type=event.event_type,
                description=desc,
                from_status=event.from_status,
                to_status=event.to_status,
                command_name=event.command_name,
                actor_id=event.actor_id,
                actor_role=event.actor_role,
                reason=event.reason,
                payload=event.payload or {},
                timestamp=event.created_at,
            )
        )

    # Messages
    all_messages: List[SupportMessageSchema] = []
    for conv in case.conversations:
        for msg in conv.messages:
            all_messages.append(
                SupportMessageSchema(
                    id=msg.id,
                    conversation_id=msg.conversation_id,
                    sender_type=msg.sender_type,
                    sender_id=msg.sender_id,
                    content=msg.content,
                    citations=msg.citations or [],
                    attachments=msg.attachments or [],
                    created_at=msg.created_at,
                )
            )
    all_messages.sort(key=lambda m: m.created_at)

    # Facts
    facts = [
        SupportExtractedFactSchema(
            id=f.id,
            fact_key=f.fact_key,
            fact_value=f.fact_value,
            confidence=f.confidence,
            source=f.source,
            verified=f.verified,
        )
        for f in case.extracted_facts
    ]

    return SupportCaseDetailResponse(
        id=case.id,
        case_number=case.case_number,
        person_id=case.person_id,
        person_name=case.person.full_name if case.person else None,
        person_phone=case.person.phone_number if case.person else None,
        person_email=case.person.email if case.person else None,
        status=case.status,
        priority=case.priority,
        category=case.category,
        subject=case.subject,
        description=case.description,
        assigned_to=case.assigned_to,
        sla_deadline=case.sla_deadline,
        is_sla_breached=breached,
        created_at=case.created_at,
        updated_at=case.updated_at,
        timeline=timeline,
        messages=all_messages,
        extracted_facts=facts,
    )


@router.post(
    "/cases/{case_id}/commands/{cmd}",
    response_model=CommandExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute named transition command (Triage, Assign, RequestInfo, Resolve, Reopen, Close)",
)
async def execute_case_command(
    case_id: uuid.UUID,
    cmd: str,
    payload: Dict[str, Any] = Body(...),
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> CommandExecutionResponse:
    """Execute named state machine transition command with strict validation and audit logging."""
    request_id = getattr(request.state, "request_id", None) if request else None
    normalized_cmd = cmd.strip().lower().replace("-", "").replace("_", "")

    command_instance: BaseCaseCommand

    if normalized_cmd == "triage":
        try:
            req = TriageCommandPayload(**payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        command_instance = TriageCommand(
            category=req.category,
            priority=req.priority,
            reason=req.reason,
        )

    elif normalized_cmd == "assign":
        try:
            req = AssignCommandPayload(**payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        command_instance = AssignCommand(
            assignee_id=req.assignee_id,
            reason=req.reason,
        )

    elif normalized_cmd in ("requestinfo", "requestinformation"):
        try:
            req = RequestInfoCommandPayload(**payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        command_instance = RequestInfoCommand(
            requested_items=req.requested_items,
            reason=req.reason,
        )

    elif normalized_cmd == "resolve":
        try:
            req = ResolveCommandPayload(**payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        command_instance = ResolveCommand(
            resolution_summary=req.resolution_summary,
            reason=req.reason,
        )

    elif normalized_cmd == "reopen":
        try:
            req = ReopenCommandPayload(**payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        command_instance = ReopenCommand(
            reason=req.reason,
        )

    elif normalized_cmd == "close":
        try:
            req = CloseCommandPayload(**payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        command_instance = CloseCommand(
            reason=req.reason,
        )

    else:
        valid_commands = ["triage", "assign", "request-info", "resolve", "reopen", "close"]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown command '{cmd}'. Valid commands are: {valid_commands}",
        )

    # Apply command through domain state machine
    case, event = await CaseService.apply_command(
        session=session,
        case_id=case_id,
        command=command_instance,
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        request_id=request_id,
    )

    return CommandExecutionResponse(
        case_id=case.id,
        case_number=case.case_number,
        command_name=command_instance.command_name,
        from_status=event.from_status or "",
        to_status=event.to_status or "",
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        executed_at=event.created_at,
        payload=event.payload or {},
    )


@router.post(
    "/cases/{case_id}/notes",
    response_model=RecordInternalNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record internal staff notes and decisions",
)
async def add_internal_note(
    case_id: uuid.UUID,
    payload: RecordInternalNoteRequest,
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> RecordInternalNoteResponse:
    """Record internal staff note or administrative decision (hidden from customer views)."""
    request_id = getattr(request.state, "request_id", None) if request else None

    case, event = await CaseService.record_internal_note(
        session=session,
        case_id=case_id,
        note=payload.note,
        decision=payload.decision,
        reason=payload.reason,
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        request_id=request_id,
    )

    return RecordInternalNoteResponse(
        case_id=case.id,
        event_id=event.id,
        event_type=event.event_type,
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        note=payload.note,
        decision=payload.decision,
        created_at=event.created_at,
    )
