import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.platform.database import GUID, Base


class AIRun(Base):
    """Persists a complete, auditable trace record of every AI execution.
    Allows exact verification, debugging, and reconstruction of grounded answers.
    """

    __tablename__ = "ai_runs"

    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID,
        ForeignKey("persons.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1.0.0")
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)

    retrieved_chunks: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    citations: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    fallback_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guardrail_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user_feedback: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_ai_runs_intent", "intent"),
        Index("ix_ai_runs_created_at", "created_at"),
    )
