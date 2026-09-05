import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.platform.audit import AuditLogger
from app.platform.embeddings import generate_deterministic_mock_embedding
from worker.tasks.ingestion import PDFIngestionPipeline


def _status_str(status_val: Union[DocumentVersionStatus, str]) -> str:
    return status_val.value if hasattr(status_val, "value") else str(status_val)


class KnowledgeService:
    """Manages the procedural knowledge base, versioning, atomic publishing,
    and rollback operations.
    """

    @classmethod
    async def create_document(
        cls,
        session: AsyncSession,
        title: str,
        category: str = "PROCEDURAL_GUIDE",
        description: Optional[str] = None,
        source_url: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: str = "support",
        request_id: Optional[str] = None,
    ) -> Document:
        """Create a new knowledge Document record or return existing with identical title."""
        stmt = select(Document).where(Document.title == title)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        doc = Document(
            title=title,
            description=description,
            category=category,
            source_url=source_url,
            metadata_json=metadata_json or {},
        )
        session.add(doc)
        await session.flush()

        await AuditLogger.record_async(
            session=session,
            action="DOCUMENT_CREATED",
            entity_type="document",
            entity_id=str(doc.id),
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            details={"title": doc.title, "category": doc.category},
        )
        return doc

    @classmethod
    async def create_draft_version(
        cls,
        session: AsyncSession,
        document_id: uuid.UUID,
        file_path: Optional[str] = None,
        content_hash: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> DocumentVersion:
        """Create a new DRAFT DocumentVersion for the given document, incrementing version_number."""
        doc = await session.get(Document, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} does not exist")

        ver_stmt = select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
        current_max = (await session.execute(ver_stmt)).scalar() or 0
        new_version_num = current_max + 1

        version = DocumentVersion(
            document_id=document_id,
            version_number=new_version_num,
            status=DocumentVersionStatus.DRAFT,
            file_path=file_path,
            content_hash=content_hash,
            metadata_json=metadata_json or {},
        )
        session.add(version)
        await session.flush()
        return version

    @classmethod
    async def ingest_version_pdf(
        cls,
        session: AsyncSession,
        version_id: uuid.UUID,
        file_source: Union[str, bytes],
        actor_id: Optional[uuid.UUID] = None,
        request_id: Optional[str] = None,
    ) -> DocumentVersion:
        """Process PDF text, chunk, embed, and store under DRAFT version."""
        return await PDFIngestionPipeline.process_and_persist_version(
            session=session,
            version_id=version_id,
            file_source=file_source,
            actor_id=actor_id,
            request_id=request_id,
        )

    @classmethod
    async def publish_version(
        cls,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: str = "supervisor",
        request_id: Optional[str] = None,
    ) -> Tuple[Document, DocumentVersion, Optional[DocumentVersion]]:
        """PUBLISHING GUARANTEE:
        Atomically retires any currently ACTIVE version and activates the target DRAFT version
        in a single database transaction. Customers never see partial or mixed version chunks.
        """
        doc = await session.get(Document, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        target_version = await session.get(DocumentVersion, version_id)
        if not target_version or target_version.document_id != document_id:
            raise ValueError(f"Version {version_id} does not belong to Document {document_id}")

        if target_version.status != DocumentVersionStatus.DRAFT:
            raise ValueError(
                f"Only DRAFT versions can be published. Current status is {_status_str(target_version.status)}"
            )

        # Ensure target version has chunks before publishing
        chunk_count = (
            await session.execute(
                select(func.count(Chunk.id)).where(Chunk.version_id == target_version.id)
            )
        ).scalar() or 0
        if chunk_count == 0:
            raise ValueError("Cannot publish a document version with 0 ingested chunks.")

        now = datetime.now(timezone.utc)

        # 1. Find and retire any currently ACTIVE version for this document
        active_stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.status == DocumentVersionStatus.ACTIVE,
        )
        current_active = (await session.execute(active_stmt)).scalar_one_or_none()

        retired_version: Optional[DocumentVersion] = None
        if current_active:
            current_active.status = DocumentVersionStatus.RETIRED
            current_active.retired_at = now
            retired_version = current_active

        # 2. Promote target DRAFT to ACTIVE
        target_version.status = DocumentVersionStatus.ACTIVE
        target_version.published_at = now
        await session.flush()

        # 3. Log publication audit event
        await AuditLogger.record_async(
            session=session,
            action="DOCUMENT_PUBLISHED",
            entity_type="document",
            entity_id=str(doc.id),
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            details={
                "title": doc.title,
                "version": target_version.version_number,
                "version_id": str(target_version.id),
                "retired_version": current_active.version_number if current_active else None,
                "status": "ACTIVE",
                "chunks_published": chunk_count,
            },
        )

        return doc, target_version, retired_version

    @classmethod
    async def rollback_version(
        cls,
        session: AsyncSession,
        document_id: uuid.UUID,
        target_version_id: Optional[uuid.UUID] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: str = "supervisor",
        request_id: Optional[str] = None,
    ) -> Tuple[Document, DocumentVersion, DocumentVersion]:
        """ATOMIC ROLLBACK:
        Atomically retires the currently ACTIVE version and restores a previously RETIRED version
        to ACTIVE in a single transaction.
        """
        doc = await session.get(Document, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        # 1. Find currently ACTIVE version
        active_stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.status == DocumentVersionStatus.ACTIVE,
        )
        current_active = (await session.execute(active_stmt)).scalar_one_or_none()
        if not current_active:
            raise ValueError(f"Document {document_id} has no currently ACTIVE version to roll back.")

        # 2. Identify target version to restore
        if target_version_id:
            target_to_restore = await session.get(DocumentVersion, target_version_id)
            if not target_to_restore or target_to_restore.document_id != document_id:
                raise ValueError(f"Target version {target_version_id} does not belong to Document {document_id}")
            if target_to_restore.status != DocumentVersionStatus.RETIRED:
                raise ValueError(
                    f"Can only rollback to a RETIRED version. Version status is {_status_str(target_to_restore.status)}"
                )
        else:
            # Pick most recently retired version
            most_recent_stmt = (
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.status == DocumentVersionStatus.RETIRED,
                )
                .order_by(desc(DocumentVersion.version_number))
                .limit(1)
            )
            target_to_restore = (await session.execute(most_recent_stmt)).scalar_one_or_none()
            if not target_to_restore:
                raise ValueError(f"No previously RETIRED version found for Document {document_id} to restore.")

        now = datetime.now(timezone.utc)

        # 3. Perform atomic switch: current active -> RETIRED, target -> ACTIVE
        current_active.status = DocumentVersionStatus.RETIRED
        current_active.retired_at = now

        target_to_restore.status = DocumentVersionStatus.ACTIVE
        target_to_restore.published_at = now
        await session.flush()

        # 4. Audit log
        await AuditLogger.record_async(
            session=session,
            action="DOCUMENT_ROLLED_BACK",
            entity_type="document",
            entity_id=str(doc.id),
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            details={
                "title": doc.title,
                "rolled_back_from_version": current_active.version_number,
                "restored_version": target_to_restore.version_number,
                "restored_version_id": str(target_to_restore.id),
            },
        )

        return doc, target_to_restore, current_active

    @classmethod
    async def get_draft_preview(
        cls,
        session: AsyncSession,
        version_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Fetch extracted chunks, token counts, and section codes for a draft version."""
        version = await session.get(
            DocumentVersion,
            version_id,
            options=[selectinload(DocumentVersion.chunks), selectinload(DocumentVersion.document)],
        )
        if not version:
            raise ValueError(f"DocumentVersion {version_id} not found")

        chunks_list = []
        for c in sorted(version.chunks, key=lambda x: x.chunk_index):
            chunks_list.append({
                "id": str(c.id),
                "chunk_index": c.chunk_index,
                "chunk_id_code": c.chunk_id_code,
                "content": c.content,
                "token_count": c.token_count,
                "metadata_json": c.metadata_json or {},
            })

        return {
            "document_id": str(version.document_id),
            "document_title": version.document.title if version.document else "",
            "version_id": str(version.id),
            "version_number": version.version_number,
            "status": _status_str(version.status),
            "total_chunks": len(chunks_list),
            "total_tokens": sum(c["token_count"] for c in chunks_list),
            "metadata_json": version.metadata_json or {},
            "chunks": chunks_list,
        }

    @classmethod
    async def test_draft_retrieval(
        cls,
        session: AsyncSession,
        version_id: uuid.UUID,
        query_text: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Preview vector search retrieval matching strictly against a DRAFT version's chunks."""
        query_embedding = generate_deterministic_mock_embedding(query_text)
        query_vec = np.array(query_embedding, dtype=np.float32)

        stmt = select(Chunk).where(Chunk.version_id == version_id)
        chunks = (await session.execute(stmt)).scalars().all()

        results = []
        for c in chunks:
            if c.embedding is not None:
                c_vec = np.array(c.embedding, dtype=np.float32)
                sim = float(np.dot(query_vec, c_vec))
                results.append((sim, c))

        results.sort(key=lambda x: x[0], reverse=True)
        top_results = results[:top_k]

        return [
            {
                "chunk_id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "chunk_id_code": chunk.chunk_id_code,
                "content": chunk.content,
                "similarity": round(sim, 4),
                "token_count": chunk.token_count,
            }
            for sim, chunk in top_results
        ]

    @classmethod
    async def list_documents(
        cls,
        session: AsyncSession,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all documents with their active version and total version count."""
        stmt = select(Document).options(selectinload(Document.versions))
        if category:
            stmt = stmt.where(Document.category == category)
        stmt = stmt.order_by(Document.created_at.desc())

        docs = (await session.execute(stmt)).scalars().all()
        result = []
        for doc in docs:
            active_ver = next(
                (v for v in doc.versions if v.status == DocumentVersionStatus.ACTIVE), None
            )
            draft_ver = next(
                (v for v in doc.versions if v.status == DocumentVersionStatus.DRAFT), None
            )
            result.append({
                "id": str(doc.id),
                "title": doc.title,
                "description": doc.description,
                "category": doc.category,
                "source_url": doc.source_url,
                "total_versions": len(doc.versions),
                "active_version_number": active_ver.version_number if active_ver else None,
                "active_version_id": str(active_ver.id) if active_ver else None,
                "has_pending_draft": draft_ver is not None,
                "pending_draft_version_id": str(draft_ver.id) if draft_ver else None,
                "created_at": doc.created_at.isoformat(),
            })
        return result

    @classmethod
    async def get_document_detail(
        cls,
        session: AsyncSession,
        document_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Get document details and all version histories."""
        doc = await session.get(
            Document,
            document_id,
            options=[selectinload(Document.versions)],
        )
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        versions_data = []
        for v in sorted(doc.versions, key=lambda x: x.version_number, reverse=True):
            versions_data.append({
                "id": str(v.id),
                "version_number": v.version_number,
                "status": _status_str(v.status),
                "content_hash": v.content_hash,
                "file_path": v.file_path,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "retired_at": v.retired_at.isoformat() if v.retired_at else None,
                "metadata_json": v.metadata_json or {},
            })

        return {
            "id": str(doc.id),
            "title": doc.title,
            "description": doc.description,
            "category": doc.category,
            "source_url": doc.source_url,
            "created_at": doc.created_at.isoformat(),
            "versions": versions_data,
        }
