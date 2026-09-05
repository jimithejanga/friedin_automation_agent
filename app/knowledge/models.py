import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.platform.database import GUID, Base
from app.platform.vector import PgVectorType


class DocumentVersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Document(Base):
    """Represents a procedural knowledge document or official handbook."""

    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="PROCEDURAL_GUIDE")
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    versions: Mapped[List["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )


class DocumentVersion(Base):
    """Represents an immutable version of a Document with publication lifecycle."""

    __tablename__ = "document_versions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[DocumentVersionStatus] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentVersionStatus.DRAFT,
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="versions")
    chunks: Mapped[List["Chunk"]] = relationship(
        "Chunk",
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )

    __table_args__ = (
        Index("ix_document_versions_doc_ver", "document_id", "version_number", unique=True),
        Index("ix_document_versions_status", "status"),
    )


class Chunk(Base):
    """Represents a text segment with vector embedding linked to a DocumentVersion."""

    __tablename__ = "chunks"

    version_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id_code: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., "Sec-2.1"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[List[float]]] = mapped_column(PgVectorType(1536), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    version: Mapped["DocumentVersion"] = relationship("DocumentVersion", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_version_idx", "version_id", "chunk_index"),
        Index("ix_chunks_id_code", "chunk_id_code"),
    )
