import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    chunk_id_code: str
    document_title: str
    content: str
    similarity_score: float
    version_id: uuid.UUID
    source_url: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": str(self.chunk_id),
            "chunk_id_code": self.chunk_id_code,
            "document_title": self.document_title,
            "source_url": self.source_url,
            "content_excerpt": self.content[:200] + ("..." if len(self.content) > 200 else ""),
            "similarity_score": round(self.similarity_score, 4),
        }


from app.platform.embeddings import generate_deterministic_mock_embedding


async def generate_embedding(text: str) -> List[float]:
    """Generate vector embedding for text using configured provider."""
    settings = get_settings()
    if settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={"input": text, "model": settings.DEFAULT_EMBEDDING_MODEL},
                )
                if res.status_code == 200:
                    data = res.json()
                    return data["data"][0]["embedding"]
        except Exception:
            # Fall back to deterministic embedding
            pass

    return generate_deterministic_mock_embedding(text, dim=settings.EMBEDDING_DIM)


class AIRetrievalService:
    """Performs cosine similarity vector retrieval against ONLY active document versions."""

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two float vectors."""
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @classmethod
    async def retrieve_active_chunks(
        cls,
        session: AsyncSession,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.05,
    ) -> List[RetrievedChunk]:
        """Query ONLY chunks associated with ACTIVE DocumentVersions,
        ranked by cosine similarity to the query embedding.
        """
        # 1. Generate query embedding
        query_vec = await generate_embedding(query)

        # 2. Query ONLY chunks linked to ACTIVE DocumentVersions
        stmt = (
            select(
                Chunk,
                Document.title.label("doc_title"),
                Document.source_url.label("doc_source_url"),
            )
            .join(DocumentVersion, Chunk.version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(DocumentVersion.status == DocumentVersionStatus.ACTIVE)
        )

        result = await session.execute(stmt)
        rows = result.all()

        if not rows:
            return []

        # 3. Compute cosine similarity
        scored_chunks: List[RetrievedChunk] = []
        for chunk, doc_title, doc_source_url in rows:
            if not chunk.embedding:
                continue

            similarity = cls.cosine_similarity(query_vec, chunk.embedding)
            if similarity >= min_similarity:
                scored_chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        chunk_id_code=chunk.chunk_id_code,
                        document_title=doc_title,
                        content=chunk.content,
                        similarity_score=similarity,
                        version_id=chunk.version_id,
                        source_url=doc_source_url,
                        metadata_json=chunk.metadata_json,
                    )
                )

        # 4. Sort descending by similarity score and take top_k
        scored_chunks.sort(key=lambda x: x.similarity_score, reverse=True)
        return scored_chunks[:top_k]
