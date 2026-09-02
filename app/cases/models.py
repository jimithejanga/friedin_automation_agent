import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database import Base, GUID


class CaseStatus(str, enum.Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    WAITING = "WAITING"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class CasePriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class MessageSenderType(str, enum.Enum):
    CUSTOMER = "customer"
    ASSISTANT = "assistant"
    SUPPORT = "support"
    SYSTEM = "system"


class Person(Base):
    __tablename__ = "persons"

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    nin_or_bvn: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    contact_preferences: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Relationships
    cases: Mapped[List["Case"]] = relationship(
        "Case",
        back_populates="person",
        cascade="all, delete-orphan",
        order_by="desc(Case.created_at)",
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="person",
        cascade="all, delete-orphan",
        order_by="desc(Conversation.created_at)",
    )


class Case(Base):
    __tablename__ = "cases"

    case_number: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, native_enum=False, length=32),
        nullable=False,
        default=CaseStatus.NEW,
        index=True,
    )
    priority: Mapped[CasePriority] = mapped_column(
        Enum(CasePriority, native_enum=False, length=32),
        nullable=False,
        default=CasePriority.NORMAL,
        index=True,
    )
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="GENERAL_INQUIRY", index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID, nullable=True, index=True
    )
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Relationships
    person: Mapped["Person"] = relationship("Person", back_populates="cases")
    events: Mapped[List["CaseEvent"]] = relationship(
        "CaseEvent",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="asc(CaseEvent.created_at)",
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="case",
        order_by="asc(Conversation.created_at)",
    )
    extracted_facts: Mapped[List["ExtractedFact"]] = relationship(
        "ExtractedFact",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="asc(ExtractedFact.created_at)",
    )


class CaseEvent(Base):
    __tablename__ = "case_events"

    case_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="STATE_TRANSITION", index=True
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    command_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID, nullable=True, index=True
    )
    actor_role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="system"
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="events")

    __table_args__ = (
        Index("ix_case_events_case_created", "case_id", "created_at"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    person_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID, ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Relationships
    person: Mapped["Person"] = relationship("Person", back_populates="conversations")
    case: Mapped[Optional["Case"]] = relationship(
        "Case", back_populates="conversations"
    )
    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="asc(Message.created_at)",
    )
    extracted_facts: Mapped[List["ExtractedFact"]] = relationship(
        "ExtractedFact",
        back_populates="conversation",
        order_by="asc(ExtractedFact.created_at)",
    )


class Message(Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MessageSenderType.CUSTOMER.value
    )
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)
    intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    attachments: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    extracted_facts: Mapped[List["ExtractedFact"]] = relationship(
        "ExtractedFact", back_populates="message"
    )

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )


class ExtractedFact(Base):
    __tablename__ = "extracted_facts"

    case_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    fact_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, default="AI_EXTRACTION"
    )
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="extracted_facts")
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation", back_populates="extracted_facts"
    )
    message: Mapped[Optional["Message"]] = relationship(
        "Message", back_populates="extracted_facts"
    )
