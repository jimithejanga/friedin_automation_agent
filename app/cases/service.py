import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
