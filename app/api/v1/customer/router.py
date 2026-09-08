import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.models import AIRun
from app.ai.router import BinaryIntentRouter, IntentType
from app.api.v1.customer.schemas import (
    AIRunDetailResponse,
    CitationSchema,
    CreateCustomerCaseRequest,
    CustomerCaseDetailResponse,
    CustomerCaseResponse,
    CustomerMessageRequest,
    CustomerMessageResponse,
    ExtractedFactSchema,
    MessageSchema,
    QuestionRequest,
    QuestionResponse,
    RequestedActionSchema,
    TimelineItemSchema,
)
from app.cases.commands import CustomerReplyCommand
from app.cases.models import (
    Case,
    CaseEvent,
    CasePriority,
    CaseStatus,
    Conversation,
    ExtractedFact,
    Message,
    MessageSenderType,
    Person,
)
from app.cases.service import CaseService
from app.platform.auth import (
    AuthenticatedUser,
    Role,
    decode_access_token,
    security_bearer,
)
from app.platform.database import get_db_session


router = APIRouter()


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
) -> Optional[AuthenticatedUser]:
    """Extract authenticated user if bearer token is present, otherwise None."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user_uuid = uuid.UUID(payload.sub)
        return AuthenticatedUser(
            id=user_uuid,
            email=payload.email,
            role=payload.role,
            is_active=True,
        )
    except Exception:
        return None


@router.post(
    "/questions",
    response_model=QuestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest customer question, execute binary routing, return grounded answer or prompt case creation",
)
async def ask_question(
    payload: QuestionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_user),
) -> QuestionResponse:
    """Ingest customer inquiry, execute binary intent routing, extract facts,
    and persist interaction in a Conversation.
    """
    # 1. Resolve Person Identity
    person: Optional[Person] = None
    if current_user:
        person = await CaseService.get_person_by_id(session, current_user.id)
        if not person:
            person = await CaseService.create_person(
                session=session,
                full_name=payload.full_name or current_user.email or "Registered Customer",
                phone_number=payload.phone_number or "+2348000000000",
                email=current_user.email,
            )
    elif payload.phone_number:
        person = await CaseService.find_person_by_contact(session, phone_number=payload.phone_number)
        if not person:
            person = await CaseService.create_person(
                session=session,
                full_name=payload.full_name or "Prospective Customer",
                phone_number=payload.phone_number,
            )
    elif payload.conversation_id:
        conv = await CaseService.get_conversation_by_id(session, payload.conversation_id)
        if conv:
            person = await CaseService.get_person_by_id(session, conv.person_id)

    if not person:
        person = await CaseService.create_person(
            session=session,
            full_name=payload.full_name or "Guest Customer",
            phone_number=payload.phone_number or "+2340000000000",
        )

    # 2. Find or Create Conversation
    conversation: Optional[Conversation] = None
    if payload.conversation_id:
        conversation = await CaseService.get_conversation_by_id(session, payload.conversation_id)

    if not conversation:
        conversation = await CaseService.create_conversation(
            session=session,
            person_id=person.id,
            channel=payload.channel,
        )

    # 3. Record Customer Message
    cust_msg = await CaseService.add_message(
        session=session,
        conversation_id=conversation.id,
        content=payload.question,
        sender_type=MessageSenderType.CUSTOMER,
        sender_id=person.id,
    )

    # 4. Execute Binary Intent Routing, Active Knowledge Retrieval & AIRun Trace Logging
    request_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None
    routing_result = await BinaryIntentRouter.route_async(
        session=session,
        question=payload.question,
        conversation_id=conversation.id,
        message_id=cust_msg.id,
        person_id=person.id,
        request_id=request_id,
    )

    # 5. Persist Extracted Facts
    for fact in routing_result.extracted_facts:
        await CaseService.add_extracted_fact(
            session=session,
            case_id=conversation.case_id or conversation.id,  # Fallback to conv ID if no case yet
            conversation_id=conversation.id,
            message_id=cust_msg.id,
            fact_key=fact.fact_key,
            fact_value=fact.fact_value,
            confidence=fact.confidence,
            source=fact.source,
        )

    # 6. Record Assistant Response Message
    citations_data = [c.to_dict() for c in routing_result.citations]
    asst_msg = await CaseService.add_message(
        session=session,
        conversation_id=conversation.id,
        content=routing_result.answer,
        sender_type=MessageSenderType.ASSISTANT,
        citations=citations_data,
        intent=routing_result.intent.value,
    )

    return QuestionResponse(
        conversation_id=conversation.id,
        message_id=asst_msg.id,
        intent=routing_result.intent.value,
        answer=routing_result.answer,
        citations=[CitationSchema(**c.to_dict()) for c in routing_result.citations],
        prompt_case_creation=routing_result.prompt_case_creation,
        suggested_category=routing_result.suggested_category,
        suggested_subject=routing_result.suggested_subject,
        extracted_facts=[
            ExtractedFactSchema(
                fact_key=f.fact_key,
                fact_value=f.fact_value,
                confidence=f.confidence,
                source=f.source,
            )
            for f in routing_result.extracted_facts
        ],
        ai_run_id=routing_result.ai_run_id,
    )


@router.post(
    "/cases",
    response_model=CustomerCaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open support case with extracted facts pre-populated from chat history",
)
async def open_case(
    payload: CreateCustomerCaseRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_user),
) -> CustomerCaseResponse:
    """Open a durable support case, automatically pre-populating extracted facts
    from conversation history without forcing the customer to repeat themselves.
    """
    request_id = getattr(request.state, "request_id", None)

    # 1. Resolve Person
    person: Optional[Person] = None
    if current_user:
        person = await CaseService.get_person_by_id(session, current_user.id)
        if not person:
            person = await CaseService.create_person(
                session=session,
                full_name=payload.full_name or current_user.email or "Registered Customer",
                phone_number=payload.phone_number or "+2348000000000",
                email=current_user.email,
                nin_or_bvn=payload.nin_or_bvn,
            )
    elif payload.conversation_id:
        conv = await CaseService.get_conversation_by_id(session, payload.conversation_id)
        if conv:
            person = await CaseService.get_person_by_id(session, conv.person_id)

    if not person:
        if not payload.phone_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer phone_number is required to open a support case.",
            )
        person = await CaseService.find_person_by_contact(
            session=session,
            phone_number=payload.phone_number,
            email=payload.email,
            nin_or_bvn=payload.nin_or_bvn,
        )
        if not person:
            person = await CaseService.create_person(
                session=session,
                full_name=payload.full_name or "Valued Customer",
                phone_number=payload.phone_number,
                email=payload.email,
                nin_or_bvn=payload.nin_or_bvn,
            )

    # 2. Create the Case
    case = await CaseService.create_case(
        session=session,
        person_id=person.id,
        subject=payload.subject,
        description=payload.description,
        category=payload.category,
        priority=payload.priority,
        metadata_json=payload.metadata_json or {},
        actor_id=person.id,
        actor_role="customer",
        request_id=request_id,
    )

    # 3. Pre-populate Extracted Facts from Conversation History
    if payload.conversation_id:
        await CaseService.link_conversation_facts_to_case(
            session=session,
            conversation_id=payload.conversation_id,
            case_id=case.id,
        )

    # 4. Attach any additional facts provided in payload
    if payload.additional_facts:
        for f in payload.additional_facts:
            await CaseService.add_extracted_fact(
                session=session,
                case_id=case.id,
                conversation_id=payload.conversation_id,
                fact_key=f.fact_key,
                fact_value=f.fact_value,
                confidence=f.confidence,
                source=f.source,
                verified=f.verified,
            )

    # 5. Fetch complete case with facts
    case_with_facts = await CaseService.get_case_by_id(session, case.id, include_facts=True)
    facts_list = [
        ExtractedFactSchema(
            fact_key=fact.fact_key,
            fact_value=fact.fact_value,
            confidence=fact.confidence,
            source=fact.source,
            verified=fact.verified,
        )
        for fact in (case_with_facts.extracted_facts if case_with_facts else [])
    ]

    return CustomerCaseResponse(
        id=case.id,
        case_number=case.case_number,
        status=case.status,
        priority=case.priority,
        category=case.category,
        subject=case.subject,
        description=case.description,
        created_at=case.created_at,
        updated_at=case.updated_at,
        extracted_facts=facts_list,
    )


def _build_case_detail_response(case: Case) -> CustomerCaseDetailResponse:
    """Helper to convert a Case domain entity into a CustomerCaseDetailResponse."""
    requested_actions_raw = CaseService.get_case_requested_actions(case)
    requested_actions = [RequestedActionSchema(**ra) for ra in requested_actions_raw]

    timeline_items: List[TimelineItemSchema] = []
    for event in case.events:
        if event.event_type.startswith("INTERNAL_"):
            continue

        desc = f"Case status updated to {event.to_status}" if event.to_status else event.event_type
        if event.event_type == "CASE_CREATED":
            desc = "Case opened"
        elif event.reason:
            desc = event.reason

        timeline_items.append(
            TimelineItemSchema(
                event_type=event.event_type,
                description=desc,
                from_status=event.from_status,
                to_status=event.to_status,
                actor_role=event.actor_role,
                timestamp=event.created_at,
                payload=event.payload or {},
            )
        )

    all_messages: List[MessageSchema] = []
    attachments: List[Any] = []
    for conv in case.conversations:
        for msg in conv.messages:
            all_messages.append(
                MessageSchema(
                    id=msg.id,
                    conversation_id=msg.conversation_id,
                    sender_type=msg.sender_type,
                    content=msg.content,
                    citations=msg.citations or [],
                    attachments=msg.attachments or [],
                    created_at=msg.created_at,
                )
            )
            if msg.attachments:
                attachments.extend(msg.attachments)

    all_messages.sort(key=lambda m: m.created_at)

    facts_list = [
        ExtractedFactSchema(
            fact_key=fact.fact_key,
            fact_value=fact.fact_value,
            confidence=fact.confidence,
            source=fact.source,
            verified=fact.verified,
        )
        for fact in case.extracted_facts
    ]

    return CustomerCaseDetailResponse(
        id=case.id,
        case_number=case.case_number,
        status=case.status,
        priority=case.priority,
        category=case.category,
        subject=case.subject,
        description=case.description,
        created_at=case.created_at,
        updated_at=case.updated_at,
        sla_deadline=case.sla_deadline,
        requested_actions=requested_actions,
        timeline=timeline_items,
        messages=all_messages,
        attachments=attachments,
        extracted_facts=facts_list,
    )


@router.get(
    "/cases/lookup",
    response_model=CustomerCaseDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Lookup case by human-readable case number",
)
async def lookup_case_by_number(
    case_number: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_user),
) -> CustomerCaseDetailResponse:
    """Retrieve full customer view of a case by case_number (e.g. CMR-20260905-XXXX)."""
    person_id = current_user.id if (current_user and current_user.role == Role.CUSTOMER) else None
    case = await CaseService.get_case_for_customer_by_number(
        session, case_number=case_number.strip(), person_id=person_id
    )
    return _build_case_detail_response(case)


@router.get(
    "/cases/{case_id}",
    response_model=CustomerCaseDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve case timeline, messages, requested actions, and attachments",
)
async def get_case_detail(
    case_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_user),
) -> CustomerCaseDetailResponse:
    """Retrieve full customer view of a case: chronological timeline,
    public messages, attachments, and pending requested actions.
    """
    person_id = current_user.id if (current_user and current_user.role == Role.CUSTOMER) else None
    case = await CaseService.get_case_for_customer(session, case_id=case_id, person_id=person_id)
    return _build_case_detail_response(case)


@router.post(
    "/cases/{case_id}/messages",
    response_model=CustomerMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit customer response (automatically shifts case from WAITING to IN_REVIEW)",
)
async def reply_to_case(
    case_id: uuid.UUID,
    payload: CustomerMessageRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_user),
) -> CustomerMessageResponse:
    """Submit a customer response to a case. If the case status is WAITING,
    automatically shifts the case to IN_REVIEW.
    """
    request_id = getattr(request.state, "request_id", None)
    person_id = current_user.id if (current_user and current_user.role == Role.CUSTOMER) else None

    # Verify case and access
    case = await CaseService.get_case_for_customer(session, case_id=case_id, person_id=person_id)

    # Find or create active conversation for this case
    conversation: Optional[Conversation] = None
    if case.conversations:
        conversation = case.conversations[0]
    else:
        conversation = await CaseService.create_conversation(
            session=session,
            person_id=case.person_id,
            case_id=case.id,
            channel="web",
        )

    # Record customer message
    msg = await CaseService.add_message(
        session=session,
        conversation_id=conversation.id,
        content=payload.content,
        sender_type=MessageSenderType.CUSTOMER,
        sender_id=case.person_id,
        attachments=payload.attachments or [],
    )

    # Automatic State Transition: If WAITING, shift to IN_REVIEW
    status_shifted = False
    if case.status == CaseStatus.WAITING:
        command = CustomerReplyCommand(
            reply_text=payload.content,
            message_id=msg.id,
            reason="Customer submitted requested information",
        )
        case, event = await CaseService.apply_command(
            session=session,
            case_id=case.id,
            command=command,
            actor_id=case.person_id,
            actor_role="customer",
            request_id=request_id,
        )
        status_shifted = True

    return CustomerMessageResponse(
        message_id=msg.id,
        conversation_id=conversation.id,
        case_id=case.id,
        content=msg.content,
        sender_type=msg.sender_type,
        created_at=msg.created_at,
        case_status=case.status,
        status_shifted_to_in_review=status_shifted,
    )


@router.get(
    "/ai-runs/{run_id}",
    response_model=AIRunDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve complete AI execution trace and verification record",
)
async def get_ai_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AIRunDetailResponse:
    """Retrieve full AI execution trace by run ID to verify model, prompt template,
    retrieved chunks, citations, tokens, latency, and boundary guardrail metrics.
    """
    airun = await session.get(AIRun, run_id)
    if not airun:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI execution trace run {run_id} not found",
        )
    return AIRunDetailResponse(
        id=airun.id,
        request_id=airun.request_id,
        conversation_id=airun.conversation_id,
        message_id=airun.message_id,
        model_name=airun.model_name,
        prompt_template_version=airun.prompt_template_version,
        intent=airun.intent,
        query_text=airun.query_text,
        raw_prompt=airun.raw_prompt,
        answer_text=airun.answer_text,
        retrieved_chunks=airun.retrieved_chunks or [],
        citations=airun.citations or [],
        input_tokens=airun.input_tokens,
        output_tokens=airun.output_tokens,
        total_tokens=airun.total_tokens,
        latency_ms=airun.latency_ms,
        fallback_triggered=airun.fallback_triggered,
        guardrail_triggered=airun.guardrail_triggered,
        created_at=airun.created_at,
    )

