import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.cases.commands import (
    AssignCommand,
    BaseCaseCommand,
    CaseCommandUnion,
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
    MessageSenderType,
    Person,
)
from app.cases.state_machine import CaseStateMachine
from app.platform.audit import AuditLogger


def generate_case_number() -> str:
    """Generate human-readable unique case number (e.g. CMR-2026-A4B7D2)."""
    year = datetime.now(timezone.utc).year
    random_suffix = secrets.token_hex(3).upper()
    return f"CMR-{year}-{random_suffix}"


class CaseService:
    """Domain service for Case management, command execution, and durable timelines."""

    @staticmethod
    async def create_person(
        session: AsyncSession,
        full_name: str,
        phone_number: str,
        email: Optional[str] = None,
        nin_or_bvn: Optional[str] = None,
        contact_preferences: Optional[Dict[str, Any]] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> Person:
        person = Person(
            full_name=full_name,
            phone_number=phone_number,
            email=email,
            nin_or_bvn=nin_or_bvn,
            contact_preferences=contact_preferences or {},
            metadata_json=metadata_json or {},
        )
        session.add(person)
        await session.flush()
        return person

    @staticmethod
    async def get_person_by_id(
        session: AsyncSession,
        person_id: uuid.UUID,
    ) -> Optional[Person]:
        result = await session.execute(select(Person).where(Person.id == person_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_case(
        session: AsyncSession,
        person_id: uuid.UUID,
        subject: str,
        description: Optional[str] = None,
        category: str = "GENERAL_INQUIRY",
        priority: CasePriority = CasePriority.NORMAL,
        metadata_json: Optional[Dict[str, Any]] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: str = "customer",
        request_id: Optional[str] = None,
    ) -> Case:
        # Verify person exists
        person = await CaseService.get_person_by_id(session, person_id)
        if not person:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Person '{person_id}' does not exist.",
            )

        case = Case(
            case_number=generate_case_number(),
            person_id=person_id,
            status=CaseStatus.NEW,
            priority=priority,
            category=category,
            subject=subject,
            description=description,
            metadata_json=metadata_json or {},
        )
        session.add(case)
        await session.flush()

        # Record initial CASE_CREATED event
        creation_event = CaseEvent(
            case_id=case.id,
            event_type="CASE_CREATED",
            from_status=None,
            to_status=CaseStatus.NEW.value,
            command_name=None,
            actor_id=actor_id or person_id,
            actor_role=actor_role,
            reason="Case opened",
            payload={"category": category, "priority": priority.value},
        )
        session.add(creation_event)
        await session.flush()

        AuditLogger.log(
            action="CASE_CREATED",
            entity_type="CASE",
            entity_id=str(case.id),
            actor_id=str(actor_id or person_id),
            actor_role=actor_role,
            request_id=request_id,
            details={"case_number": case.case_number, "subject": subject},
        )

        return case

    @staticmethod
    async def get_case_by_id(
        session: AsyncSession,
        case_id: uuid.UUID,
        include_events: bool = True,
        include_facts: bool = False,
    ) -> Optional[Case]:
        query = select(Case).where(Case.id == case_id)
        if include_events:
            query = query.options(selectinload(Case.events))
        if include_facts:
            query = query.options(selectinload(Case.extracted_facts))
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def apply_command(
        session: AsyncSession,
        case_id: uuid.UUID,
        command: BaseCaseCommand,
        actor_id: Optional[uuid.UUID],
        actor_role: str,
        request_id: Optional[str] = None,
    ) -> tuple[Case, CaseEvent]:
        """Atomically execute a transition command, update the case, and write an immutable CaseEvent."""
        case = await CaseService.get_case_by_id(session, case_id, include_events=True)
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case '{case_id}' not found.",
            )

        payload = command.to_payload()
        command_name = command.command_name

        # State machine transition and validation
        from_status, to_status = CaseStateMachine.apply_transition(
            case=case,
            command_name=command_name,
            actor_role=actor_role,
            payload=payload,
        )

        # Write immutable timeline event
        event = CaseEvent(
            case=case,
            case_id=case.id,
            event_type="STATE_TRANSITION",
            from_status=from_status.value,
            to_status=to_status.value,
            command_name=command_name,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=command.reason,
            payload=payload,
        )
        session.add(event)
        await session.flush()

        # Audit log
        AuditLogger.log(
            action=f"CASE_COMMAND_{command_name.upper()}",
            entity_type="CASE",
            entity_id=str(case.id),
            actor_id=str(actor_id) if actor_id else None,
            actor_role=actor_role,
            request_id=request_id,
            details={
                "from_status": from_status.value,
                "to_status": to_status.value,
                "command": command_name,
                "payload": payload,
            },
        )

        return case, event

    @staticmethod
    async def add_extracted_fact(
        session: AsyncSession,
        case_id: uuid.UUID,
        fact_key: str,
        fact_value: str,
        confidence: float = 1.0,
        source: str = "AI_EXTRACTION",
        verified: bool = False,
        conversation_id: Optional[uuid.UUID] = None,
        message_id: Optional[uuid.UUID] = None,
    ) -> ExtractedFact:
        fact = ExtractedFact(
            case_id=case_id,
            conversation_id=conversation_id,
            message_id=message_id,
            fact_key=fact_key,
            fact_value=fact_value,
            confidence=confidence,
            source=source,
            verified=verified,
        )
        session.add(fact)
        await session.flush()
        return fact

    @staticmethod
    async def create_conversation(
        session: AsyncSession,
        person_id: uuid.UUID,
        case_id: Optional[uuid.UUID] = None,
        channel: str = "web",
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> Conversation:
        conv = Conversation(
            person_id=person_id,
            case_id=case_id,
            channel=channel,
            metadata_json=metadata_json or {},
        )
        session.add(conv)
        await session.flush()
        return conv

    @staticmethod
    async def add_message(
        session: AsyncSession,
        conversation_id: uuid.UUID,
        content: str,
        sender_type: MessageSenderType | str = MessageSenderType.CUSTOMER,
        sender_id: Optional[uuid.UUID] = None,
        citations: Optional[List[Any]] = None,
        intent: Optional[str] = None,
        attachments: Optional[List[Any]] = None,
    ) -> Message:
        sender_type_val = (
            sender_type.value
            if isinstance(sender_type, MessageSenderType)
            else str(sender_type)
        )
        msg = Message(
            conversation_id=conversation_id,
            content=content,
            sender_type=sender_type_val,
            sender_id=sender_id,
            citations=citations or [],
            intent=intent,
            attachments=attachments or [],
        )
        session.add(msg)
        await session.flush()
        return msg

    @staticmethod
    async def get_conversation_by_id(
        session: AsyncSession,
        conversation_id: uuid.UUID,
        include_messages: bool = True,
        include_facts: bool = True,
    ) -> Optional[Conversation]:
        query = select(Conversation).where(Conversation.id == conversation_id)
        if include_messages:
            query = query.options(selectinload(Conversation.messages))
        if include_facts:
            query = query.options(selectinload(Conversation.extracted_facts))
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def find_person_by_contact(
        session: AsyncSession,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
        nin_or_bvn: Optional[str] = None,
    ) -> Optional[Person]:
        """Find existing Person by phone, email, or NIN."""
        if phone_number:
            res = await session.execute(select(Person).where(Person.phone_number == phone_number))
            p = res.scalar_one_or_none()
            if p:
                return p
        if email:
            res = await session.execute(select(Person).where(Person.email == email))
            p = res.scalar_one_or_none()
            if p:
                return p
        if nin_or_bvn:
            res = await session.execute(select(Person).where(Person.nin_or_bvn == nin_or_bvn))
            p = res.scalar_one_or_none()
            if p:
                return p
        return None

    @staticmethod
    async def link_conversation_facts_to_case(
        session: AsyncSession,
        conversation_id: uuid.UUID,
        case_id: uuid.UUID,
    ) -> List[ExtractedFact]:
        """Associate a conversation and its pre-extracted facts with a case without re-typing."""
        # 1. Update conversation link
        conv_res = await session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = conv_res.scalar_one_or_none()
        if conv:
            conv.case_id = case_id

        # 2. Update facts
        facts_res = await session.execute(
            select(ExtractedFact).where(ExtractedFact.conversation_id == conversation_id)
        )
        facts = list(facts_res.scalars().all())
        for fact in facts:
            fact.case_id = case_id
        await session.flush()
        return facts

    @staticmethod
    async def get_case_for_customer(
        session: AsyncSession,
        case_id: uuid.UUID,
        person_id: Optional[uuid.UUID] = None,
    ) -> Case:
        """Fetch case with events, facts, conversations, and messages, enforcing customer isolation."""
        query = (
            select(Case)
            .where(Case.id == case_id)
            .options(
                selectinload(Case.events),
                selectinload(Case.extracted_facts),
                selectinload(Case.conversations).selectinload(Conversation.messages),
            )
        )
        result = await session.execute(query)
        case = result.scalar_one_or_none()
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case '{case_id}' not found.",
            )

        if person_id is not None and case.person_id != person_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permission to access this case.",
            )

        return case

    @staticmethod
    async def get_case_for_customer_by_number(
        session: AsyncSession,
        case_number: str,
        person_id: Optional[uuid.UUID] = None,
    ) -> Case:
        """Fetch case by human-readable case_number, enforcing customer isolation."""
        query = (
            select(Case)
            .where(Case.case_number == case_number)
            .options(
                selectinload(Case.events),
                selectinload(Case.extracted_facts),
                selectinload(Case.conversations).selectinload(Conversation.messages),
            )
        )
        result = await session.execute(query)
        case = result.scalar_one_or_none()
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case with number '{case_number}' not found.",
            )

        if person_id is not None and case.person_id != person_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permission to access this case.",
            )

        return case


    @staticmethod
    def get_case_requested_actions(case: Case) -> List[Dict[str, Any]]:
        """Inspect case state and history to provide explicit requested actions when WAITING."""
        if case.status != CaseStatus.WAITING:
            return []

        # Find latest RequestInfo event
        for event in reversed(case.events):
            if event.command_name == "RequestInfo" or event.to_status == CaseStatus.WAITING.value:
                payload = event.payload or {}
                return [
                    {
                        "action_type": payload.get("action", "PROVIDE_INFORMATION"),
                        "reason": event.reason or "Support specialist requested additional information or documentation.",
                        "requested_fields": payload.get("requested_items") or payload.get("requested_info"),
                        "payload": payload,
                        "requested_at": event.created_at.isoformat() if event.created_at else None,
                    }
                ]

        return [
            {
                "action_type": "PROVIDE_INFORMATION",
                "reason": "Support specialist is awaiting customer response to proceed.",
                "requested_fields": None,
                "payload": {},
                "requested_at": case.updated_at.isoformat() if case.updated_at else None,
            }
        ]

    @staticmethod
    async def search_people(
        session: AsyncSession,
        query: Optional[str] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
        nin_or_bvn: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, List[Person]]:
        """Search people cross-case by name, phone, email, or identity identifier, loading associated cases."""
        stmt = select(Person).options(selectinload(Person.cases))
        filters = []
        if query:
            q_clean = f"%{query.strip()}%"
            filters.append(
                or_(
                    Person.full_name.ilike(q_clean),
                    Person.phone_number.ilike(q_clean),
                    Person.email.ilike(q_clean),
                    Person.nin_or_bvn.ilike(q_clean),
                )
            )
        if phone_number:
            filters.append(Person.phone_number.ilike(f"%{phone_number.strip()}%"))
        if email:
            filters.append(Person.email.ilike(f"%{email.strip()}%"))
        if nin_or_bvn:
            filters.append(Person.nin_or_bvn.ilike(f"%{nin_or_bvn.strip()}%"))

        if filters:
            stmt = stmt.where(and_(*filters))

        count_stmt = select(func.count(Person.id))
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total_res = await session.execute(count_stmt)
        total = total_res.scalar() or 0

        stmt = stmt.order_by(desc(Person.created_at)).limit(limit).offset(offset)
        result = await session.execute(stmt)
        people = list(result.scalars().unique().all())
        return total, people

    @staticmethod
    async def filter_cases(
        session: AsyncSession,
        status: Optional[CaseStatus] = None,
        priority: Optional[CasePriority] = None,
        category: Optional[str] = None,
        assignee_id: Optional[uuid.UUID] = None,
        unassigned_only: bool = False,
        sla_breached: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, List[Case]]:
        """Filter case queues by status, priority, category, assignee, and SLA deadline."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(Case)
            .options(
                joinedload(Case.person),
                selectinload(Case.events),
            )
        )
        filters = []
        if status:
            stmt = stmt.where(Case.status == status)
            filters.append(Case.status == status)
        if priority:
            stmt = stmt.where(Case.priority == priority)
            filters.append(Case.priority == priority)
        if category:
            stmt = stmt.where(Case.category.ilike(f"%{category.strip()}%"))
            filters.append(Case.category.ilike(f"%{category.strip()}%"))
        if unassigned_only:
            stmt = stmt.where(Case.assigned_to.is_(None))
            filters.append(Case.assigned_to.is_(None))
        elif assignee_id:
            stmt = stmt.where(Case.assigned_to == assignee_id)
            filters.append(Case.assigned_to == assignee_id)

        if sla_breached is True:
            sla_cond = and_(
                Case.sla_deadline.isnot(None),
                Case.sla_deadline < now,
                Case.status.notin_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
            )
            stmt = stmt.where(sla_cond)
            filters.append(sla_cond)
        elif sla_breached is False:
            sla_cond = or_(
                Case.sla_deadline.is_(None),
                Case.sla_deadline >= now,
                Case.status.in_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
            )
            stmt = stmt.where(sla_cond)
            filters.append(sla_cond)

        if search:
            s_term = f"%{search.strip()}%"
            search_cond = or_(
                Case.case_number.ilike(s_term),
                Case.subject.ilike(s_term),
                Case.description.ilike(s_term),
            )
            stmt = stmt.where(search_cond)
            filters.append(search_cond)

        count_stmt = select(func.count(Case.id))
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total_res = await session.execute(count_stmt)
        total = total_res.scalar() or 0

        stmt = stmt.order_by(desc(Case.created_at)).limit(limit).offset(offset)
        result = await session.execute(stmt)
        cases = list(result.scalars().unique().all())
        return total, cases

    @staticmethod
    async def record_internal_note(
        session: AsyncSession,
        case_id: uuid.UUID,
        note: str,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: str = "support",
        request_id: Optional[str] = None,
    ) -> tuple[Case, CaseEvent]:
        """Record an internal staff note and decision on a case (hidden from customer views)."""
        case = await CaseService.get_case_by_id(session, case_id, include_events=True)
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case '{case_id}' not found.",
            )

        payload = {"note": note}
        if decision:
            payload["decision"] = decision

        event = CaseEvent(
            case=case,
            case_id=case.id,
            event_type="INTERNAL_NOTE",
            from_status=case.status.value,
            to_status=case.status.value,
            command_name="InternalNote",
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason or "Internal staff note recorded",
            payload=payload,
        )
        session.add(event)
        await session.flush()

        AuditLogger.log(
            action="CASE_INTERNAL_NOTE",
            entity_type="CASE",
            entity_id=str(case.id),
            actor_id=str(actor_id) if actor_id else None,
            actor_role=actor_role,
            request_id=request_id,
            details={"decision": decision, "note_length": len(note)},
        )
        return case, event

    @staticmethod
    async def get_case_for_support(
        session: AsyncSession,
        case_id: uuid.UUID,
    ) -> Case:
        """Fetch complete case history for support staff, including internal notes and staff decisions."""
        query = (
            select(Case)
            .where(Case.id == case_id)
            .options(
                joinedload(Case.person),
                selectinload(Case.events),
                selectinload(Case.extracted_facts),
                selectinload(Case.conversations).selectinload(Conversation.messages),
            )
        )
        result = await session.execute(query)
        case = result.scalar_one_or_none()
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case '{case_id}' not found.",
            )
        return case


