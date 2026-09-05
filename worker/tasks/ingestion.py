import io
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pypdf
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.platform.audit import AuditLogger
from app.platform.embeddings import generate_deterministic_mock_embedding
from app.platform.database import get_session_factory

logger = structlog.get_logger("cmr.worker.ingestion")


class PDFIngestionPipeline:
    """Extracts text from procedural PDF documents, creates semantic chunks
    with deterministic section codes, generates 1536-dim vector embeddings,
    and attaches them to a DocumentVersion.
    """

    @classmethod
    def extract_text_from_pdf(cls, file_source: Union[str, Path, bytes]) -> List[Dict[str, Any]]:
        """Extract text page-by-page from a PDF file path or raw bytes."""
        if isinstance(file_source, (str, Path)):
            with open(file_source, "rb") as f:
                reader = pypdf.PdfReader(f)
                return cls._read_pdf_pages(reader)
        elif isinstance(file_source, bytes):
            reader = pypdf.PdfReader(io.BytesIO(file_source))
            return cls._read_pdf_pages(reader)
        else:
            raise ValueError(f"Unsupported file_source type: {type(file_source)}")

    @classmethod
    def _read_pdf_pages(cls, reader: pypdf.PdfReader) -> List[Dict[str, Any]]:
        pages_data = []
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages_data.append({
                "page_number": page_idx + 1,
                "text": text.strip(),
            })
        return pages_data

    @classmethod
    def chunk_extracted_pages(
        cls,
        pages_data: List[Dict[str, Any]],
        document_title: str,
        target_token_size: int = 250,
    ) -> List[Dict[str, Any]]:
        """Splits extracted page text into coherent semantic chunks.
        Detects headings or section demarcations, assigns structured codes (e.g. 'Sec-1.1'),
        and estimates token counts.
        """
        chunks: List[Dict[str, Any]] = []
        global_chunk_idx = 0

        section_pattern = re.compile(
            r"(?:Section|Sec\.?|Part|Article|Chapter)\s+([0-9A-Za-z\.-]+)",
            re.IGNORECASE,
        )

        for page in pages_data:
            page_num = page["page_number"]
            raw_text = page["text"]
            if not raw_text:
                continue

            # Split text by double newlines into paragraphs
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]

            current_section_code = f"Sec-{page_num}.1"
            current_buffer: List[str] = []
            current_tokens = 0
            page_chunk_sub_idx = 1

            for para in paragraphs:
                # Check for explicit section header in paragraph
                sec_match = section_pattern.search(para)
                if sec_match:
                    found_code = sec_match.group(1).strip()
                    current_section_code = f"Sec-{found_code}"

                # Approx tokens: word count * 1.3
                para_tokens = max(1, int(len(para.split()) * 1.3))

                if current_buffer and (current_tokens + para_tokens > target_token_size):
                    chunk_text = " ".join(current_buffer)
                    chunks.append({
                        "chunk_index": global_chunk_idx,
                        "chunk_id_code": current_section_code,
                        "content": chunk_text,
                        "token_count": current_tokens,
                        "metadata_json": {
                            "document_title": document_title,
                            "page_number": page_num,
                            "section": current_section_code,
                        },
                    })
                    global_chunk_idx += 1
                    page_chunk_sub_idx += 1
                    current_section_code = f"Sec-{page_num}.{page_chunk_sub_idx}"
                    current_buffer = [para]
                    current_tokens = para_tokens
                else:
                    current_buffer.append(para)
                    current_tokens += para_tokens

            if current_buffer:
                chunk_text = " ".join(current_buffer)
                chunks.append({
                    "chunk_index": global_chunk_idx,
                    "chunk_id_code": current_section_code,
                    "content": chunk_text,
                    "token_count": current_tokens,
                    "metadata_json": {
                        "document_title": document_title,
                        "page_number": page_num,
                        "section": current_section_code,
                    },
                })
                global_chunk_idx += 1

        # Fallback if document had no text
        if not chunks:
            chunks.append({
                "chunk_index": 0,
                "chunk_id_code": "Sec-1.0",
                "content": f"Document: {document_title}. No selectable text extracted from PDF.",
                "token_count": 10,
                "metadata_json": {"document_title": document_title, "page_number": 1},
            })

        return chunks

    @classmethod
    async def process_and_persist_version(
        cls,
        session: AsyncSession,
        version_id: uuid.UUID,
        file_source: Union[str, Path, bytes],
        request_id: Optional[str] = None,
        actor_id: Optional[uuid.UUID] = None,
    ) -> DocumentVersion:
        """Parses the PDF, chunks text, computes embeddings, and persists chunks
        under the specified DocumentVersion.
        """
        start_time = time.perf_counter()

        # 1. Fetch version and document
        version = await session.get(DocumentVersion, version_id)
        if not version:
            raise ValueError(f"DocumentVersion {version_id} not found")

        doc = await session.get(Document, version.document_id)
        if not doc:
            raise ValueError(f"Parent Document {version.document_id} not found")

        # 2. Extract text
        pages_data = cls.extract_text_from_pdf(file_source)
        total_pages = len(pages_data)

        # 3. Chunk text
        chunks_data = cls.chunk_extracted_pages(pages_data, document_title=doc.title)

        # 4. Remove any existing chunks for this version (in case of re-ingestion)
        existing_chunks_stmt = select(Chunk).where(Chunk.version_id == version.id)
        existing_chunks = (await session.execute(existing_chunks_stmt)).scalars().all()
        for ec in existing_chunks:
            await session.delete(ec)
        await session.flush()

        # 5. Generate embeddings and persist chunks
        total_tokens = 0
        persisted_chunks: List[Chunk] = []

        for c_data in chunks_data:
            embedding = generate_deterministic_mock_embedding(c_data["content"])
            chunk = Chunk(
                version_id=version.id,
                chunk_index=c_data["chunk_index"],
                chunk_id_code=c_data["chunk_id_code"],
                content=c_data["content"],
                embedding=embedding,
                token_count=c_data["token_count"],
                metadata_json=c_data["metadata_json"],
            )
            session.add(chunk)
            persisted_chunks.append(chunk)
            total_tokens += c_data["token_count"]

        # 6. Update version metadata
        version_meta = dict(version.metadata_json or {})
        elapsed_sec = round(time.perf_counter() - start_time, 3)
        version_meta.update({
            "total_pages": total_pages,
            "total_chunks": len(persisted_chunks),
            "total_tokens": total_tokens,
            "ingestion_duration_sec": elapsed_sec,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })
        version.metadata_json = version_meta
        await session.flush()

        # 7. Audit log
        await AuditLogger.record_async(
            session=session,
            action="DOCUMENT_INGESTED",
            entity_type="document_version",
            entity_id=str(version.id),
            actor_id=actor_id,
            actor_role="system",
            request_id=request_id,
            details={
                "document_id": str(doc.id),
                "document_title": doc.title,
                "version_number": version.version_number,
                "total_pages": total_pages,
                "total_chunks": len(persisted_chunks),
                "total_tokens": total_tokens,
                "duration_sec": elapsed_sec,
            },
        )

        logger.info(
            "document_ingestion_completed",
            document_id=str(doc.id),
            version_id=str(version.id),
            chunks=len(persisted_chunks),
            tokens=total_tokens,
            duration=elapsed_sec,
        )

        return version


async def ingest_document_version_task(
    version_id: uuid.UUID,
    file_path: str,
    request_id: Optional[str] = None,
    session_factory=None,
) -> None:
    """Standalone background task entrypoint suitable for worker invocation."""
    if session_factory is None:
        session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            await PDFIngestionPipeline.process_and_persist_version(
                session=session,
                version_id=version_id,
                file_source=file_path,
                request_id=request_id,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error("ingest_document_version_task_failed", version_id=str(version_id), error=str(exc))
            raise
