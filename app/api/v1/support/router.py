import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.support.knowledge_schemas import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentSummarySchema,
    DocumentUploadResponse,
    DocumentVersionItemSchema,
    DraftChunkItemSchema,
    DraftPreviewResponse,
    DraftRetrievalMatchSchema,
    DraftRetrievalTestRequest,
    DraftRetrievalTestResponse,
    PublishVersionResponse,
    RollbackVersionResponse,
)

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
from app.config import get_settings
from app.knowledge.service import KnowledgeService
from app.platform.auth import AuthenticatedUser, Role, require_roles
from app.platform.database import get_db_session

router = APIRouter()

SUPPORT_ROLES = (Role.SUPPORT, Role.SUPERVISOR, Role.ADMIN)
ADMIN_SUPERVISOR_ROLES = (Role.SUPERVISOR, Role.ADMIN)


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


# -----------------------------------------------------------------------------
# Knowledge Base & Vector Publishing Endpoints (Phase 4)
# -----------------------------------------------------------------------------

@router.post(
    "/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload procedural PDF document, extract text, generate chunks & embeddings into DRAFT",
)
async def upload_document_pdf(
    file: UploadFile = File(..., description="Procedural PDF document"),
    title: str = Form(..., description="Document title"),
    category: str = Form("PROCEDURAL_GUIDE", description="Document category"),
    description: Optional[str] = Form(None, description="Document description"),
    source_url: Optional[str] = Form(None, description="Official source reference URL"),
    publish_immediately: bool = Form(False, description="Whether to atomically publish immediately after ingestion"),
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> DocumentUploadResponse:
    """Upload a raw PDF document, compute content hash, create a DRAFT version,
    extract text page-by-page, generate semantic chunks with vector embeddings,
    and optionally publish atomically.
    """
    request_id = getattr(request.state, "request_id", None) if request else None

    # Read PDF content & compute SHA-256 hash
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    content_hash = hashlib.sha256(content).hexdigest()

    # 1. Create or fetch Document
    doc = await KnowledgeService.create_document(
        session=session,
        title=title,
        category=category,
        description=description,
        source_url=source_url,
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        request_id=request_id,
    )

    # 2. Save file to storage
    settings = get_settings()
    storage_dir = Path(settings.STORAGE_LOCAL_DIR) / str(doc.id)
    storage_dir.mkdir(parents=True, exist_ok=True)

    # 3. Create DRAFT DocumentVersion
    draft_ver = await KnowledgeService.create_draft_version(
        session=session,
        document_id=doc.id,
        content_hash=content_hash,
    )

    saved_path = storage_dir / f"v{draft_ver.version_number}.pdf"
    saved_path.write_bytes(content)
    draft_ver.file_path = str(saved_path)
    await session.flush()

    # 4. Ingest PDF: parse, chunk, embed
    try:
        draft_ver = await KnowledgeService.ingest_version_pdf(
            session=session,
            version_id=draft_ver.id,
            file_source=content,
            actor_id=current_user.id,
            request_id=request_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"PDF parsing or chunk extraction failed: {exc}",
        )

    # 5. Atomic publish if requested
    is_published = False
    if publish_immediately:
        if current_user.role not in ADMIN_SUPERVISOR_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Immediate publishing requires SUPERVISOR or ADMIN role.",
            )
        doc, draft_ver, _ = await KnowledgeService.publish_version(
            session=session,
            document_id=doc.id,
            version_id=draft_ver.id,
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            request_id=request_id,
        )
        is_published = True

    meta = draft_ver.metadata_json or {}
    total_chunks = meta.get("total_chunks", 0)
    total_tokens = meta.get("total_tokens", 0)

    return DocumentUploadResponse(
        document_id=doc.id,
        title=doc.title,
        version_id=draft_ver.id,
        version_number=draft_ver.version_number,
        status=getattr(draft_ver.status, "value", str(draft_ver.status)),
        content_hash=content_hash,
        total_chunks=total_chunks,
        total_tokens=total_tokens,
        is_published=is_published,
        message=(
            f"Document version {draft_ver.version_number} uploaded and atomically published."
            if is_published
            else f"Document version {draft_ver.version_number} ingested in DRAFT status. Ready for review."
        ),
    )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all procedural knowledge documents with active and draft version details",
)
async def list_documents(
    category: Optional[str] = Query(None, description="Filter by document category"),
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> DocumentListResponse:
    """Retrieve catalog of procedural documents with active version and pending draft counts."""
    docs = await KnowledgeService.list_documents(session, category=category)
    summaries = [DocumentSummarySchema(**d) for d in docs]
    return DocumentListResponse(total=len(summaries), documents=summaries)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve document metadata and all historic versions",
)
async def get_document_detail(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> DocumentDetailResponse:
    """Retrieve full detail for a document including versions, statuses, hashes, and dates."""
    try:
        detail = await KnowledgeService.get_document_detail(session, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DocumentDetailResponse(**detail)


@router.get(
    "/documents/{document_id}/versions/{version_id}/preview",
    response_model=DraftPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview extracted chunks, token counts, and section codes for a draft version",
)
async def preview_draft_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> DraftPreviewResponse:
    """Preview semantic chunks, section codes, and token counts of a draft version prior to activation."""
    try:
        preview_data = await KnowledgeService.get_draft_preview(session, version_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DraftPreviewResponse(**preview_data)


@router.post(
    "/documents/{document_id}/versions/{version_id}/test-query",
    response_model=DraftRetrievalTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Test vector retrieval relevance against draft chunks before publishing",
)
async def test_draft_query(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: DraftRetrievalTestRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*SUPPORT_ROLES)),
) -> DraftRetrievalTestResponse:
    """Execute isolated vector similarity search against chunks of a draft version."""
    matches_raw = await KnowledgeService.test_draft_retrieval(
        session=session,
        version_id=version_id,
        query_text=payload.query,
        top_k=payload.top_k,
    )
    matches = [DraftRetrievalMatchSchema(**m) for m in matches_raw]
    return DraftRetrievalTestResponse(
        version_id=version_id,
        query=payload.query,
        matches=matches,
    )


@router.post(
    "/documents/{document_id}/versions/{version_id}/publish",
    response_model=PublishVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Atomically publish a DRAFT version and retire previous ACTIVE version",
)
async def publish_draft_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*ADMIN_SUPERVISOR_ROLES)),
) -> PublishVersionResponse:
    """PUBLISHING GUARANTEE:
    Atomically retires the current ACTIVE version and activates the target DRAFT version
    in a single database transaction. Customers immediately retrieve from the new version.
    """
    request_id = getattr(request.state, "request_id", None) if request else None
    try:
        doc, published_ver, retired_ver = await KnowledgeService.publish_version(
            session=session,
            document_id=document_id,
            version_id=version_id,
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            request_id=request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return PublishVersionResponse(
        document_id=doc.id,
        document_title=doc.title,
        published_version_id=published_ver.id,
        published_version_number=published_ver.version_number,
        status=getattr(published_ver.status, "value", str(published_ver.status)),
        retired_version_number=retired_ver.version_number if retired_ver else None,
        published_at=published_ver.published_at.isoformat() if published_ver.published_at else "",
        message=(
            f"Version {published_ver.version_number} is now ACTIVE. "
            + (f"Version {retired_ver.version_number} has been RETIRED." if retired_ver else "First version activated.")
        ),
    )


@router.post(
    "/documents/{document_id}/rollback",
    response_model=RollbackVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Atomically roll back current ACTIVE version to a previous RETIRED version",
)
async def rollback_document_version(
    document_id: uuid.UUID,
    target_version_id: Optional[uuid.UUID] = Query(None, description="Optional specific version ID to restore"),
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_roles(*ADMIN_SUPERVISOR_ROLES)),
) -> RollbackVersionResponse:
    """ATOMIC ROLLBACK:
    Atomically retires the active version and restores a previously RETIRED version.
    Customer queries immediately fail back to the restored version.
    """
    request_id = getattr(request.state, "request_id", None) if request else None
    try:
        doc, restored_ver, retired_ver = await KnowledgeService.rollback_version(
            session=session,
            document_id=document_id,
            target_version_id=target_version_id,
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            request_id=request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return RollbackVersionResponse(
        document_id=doc.id,
        document_title=doc.title,
        restored_version_id=restored_ver.id,
        restored_version_number=restored_ver.version_number,
        retired_version_number=retired_ver.version_number,
        status=getattr(restored_ver.status, "value", str(restored_ver.status)),
        message=(
            f"Rollback successful: Version {restored_ver.version_number} restored to ACTIVE. "
            f"Version {retired_ver.version_number} RETIRED."
        ),
    )
