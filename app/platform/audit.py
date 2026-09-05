import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field
import structlog


logger = structlog.get_logger("cmr.audit")

# PII Regex Patterns
BVN_PATTERN = re.compile(r"\b\d{11}\b")  # 11 digit Nigerian BVN/NIN
CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b|\b\d{13,19}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
SECRET_KEYS_PATTERN = re.compile(
    r"(?i)(password|secret|token|authorization|bearer|pin|cvv|api_key|access_token|refresh_token)"
)


def mask_string(text: str) -> str:
    """Mask sensitive PII strings like BVN, card numbers, tokens."""
    if not isinstance(text, str):
        return text

    # Mask card numbers (leave last 4)
    def _mask_card(match: re.Match) -> str:
        s = match.group(0).replace(" ", "").replace("-", "")
        if len(s) >= 13:
            return f"****-****-****-{s[-4:]}"
        return "****"

    # Mask 11-digit BVN / NIN (leave first 2 and last 2)
    def _mask_bvn_nin(match: re.Match) -> str:
        s = match.group(0)
        return f"{s[:2]}*******{s[-2:]}"

    text = CARD_PATTERN.sub(_mask_card, text)
    text = BVN_PATTERN.sub(_mask_bvn_nin, text)
    return text


def mask_pii(data: Any) -> Any:
    """Recursively mask PII in dictionaries, lists, and strings."""
    if isinstance(data, dict):
        masked_dict = {}
        for k, v in data.items():
            if isinstance(k, str) and SECRET_KEYS_PATTERN.search(k):
                masked_dict[k] = "[REDACTED]"
            else:
                masked_dict[k] = mask_pii(v)
        return masked_dict
    elif isinstance(data, list):
        return [mask_pii(item) for item in data]
    elif isinstance(data, str):
        return mask_string(data)
    return data


class AuditEvent(BaseModel):
    """Structured append-only audit event schema."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON
from sqlalchemy.ext.asyncio import AsyncSession
from app.platform.database import GUID, Base


class DbAuditEvent(Base):
    """Durable append-only audit event stored in database for compliance,
    incident investigation, and operator dashboards with guaranteed PII masking.
    """

    __tablename__ = "audit_events"

    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID, nullable=True, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False, default="system", index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_events_req_time", "request_id", "timestamp"),
    )


class AuditLogger:
    """Audit Sink for recording append-only compliance events with guaranteed PII masking."""

    @staticmethod
    def log(
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor_id: str | None = None,
        actor_role: str | None = None,
        request_id: str | None = None,
        details: Dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> AuditEvent:
        clean_details = mask_pii(details or {})
        
        event = AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            details=clean_details,
            ip_address=ip_address,
        )

        logger.info(
            "audit_event_recorded",
            audit_id=str(event.id),
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            request_id=event.request_id,
            details=event.details,
            ip_address=event.ip_address,
            timestamp=event.timestamp.isoformat(),
        )
        return event

    @classmethod
    async def record_async(
        cls,
        session: AsyncSession,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor_id: uuid.UUID | str | None = None,
        actor_role: str | None = None,
        request_id: str | None = None,
        details: Dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> DbAuditEvent:
        """Persists PII-masked audit event into the database and writes structured log."""
        clean_details = mask_pii(details or {})
        actor_uuid = None
        if actor_id:
            try:
                actor_uuid = uuid.UUID(str(actor_id))
            except Exception:
                actor_uuid = None

        db_event = DbAuditEvent(
            request_id=request_id,
            actor_id=actor_uuid,
            actor_role=actor_role or "system",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            details=clean_details,
            ip_address=ip_address,
        )
        session.add(db_event)
        await session.flush()

        logger.info(
            "audit_event_recorded",
            audit_id=str(db_event.id),
            action=db_event.action,
            entity_type=db_event.entity_type,
            entity_id=db_event.entity_id,
            actor_id=str(db_event.actor_id) if db_event.actor_id else None,
            actor_role=db_event.actor_role,
            request_id=db_event.request_id,
            details=db_event.details,
            ip_address=db_event.ip_address,
            timestamp=db_event.timestamp.isoformat(),
        )
        return db_event

