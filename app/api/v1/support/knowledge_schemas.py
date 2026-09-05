import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentSummarySchema(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    category: str
    source_url: Optional[str] = None
    total_versions: int
    active_version_number: Optional[int] = None
    active_version_id: Optional[uuid.UUID] = None
    has_pending_draft: bool = False
    pending_draft_version_id: Optional[uuid.UUID] = None
    created_at: str


class DocumentListResponse(BaseModel):
    total: int
    documents: List[DocumentSummarySchema]


class DocumentVersionItemSchema(BaseModel):
    id: uuid.UUID
    version_number: int
    status: str
    content_hash: Optional[str] = None
    file_path: Optional[str] = None
    published_at: Optional[str] = None
    retired_at: Optional[str] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class DocumentDetailResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    category: str
    source_url: Optional[str] = None
    created_at: str
    versions: List[DocumentVersionItemSchema] = Field(default_factory=list)


class DraftChunkItemSchema(BaseModel):
    id: str
    chunk_index: int
    chunk_id_code: str
    content: str
    token_count: int
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class DraftPreviewResponse(BaseModel):
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    version_number: int
    status: str
    total_chunks: int
    total_tokens: int
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    chunks: List[DraftChunkItemSchema] = Field(default_factory=list)


class DraftRetrievalTestRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Test query to evaluate draft relevance")
    top_k: int = Field(default=3, ge=1, le=10, description="Number of top chunks to return")


class DraftRetrievalMatchSchema(BaseModel):
    chunk_id: str
    chunk_index: int
    chunk_id_code: str
    content: str
    similarity: float
    token_count: int


class DraftRetrievalTestResponse(BaseModel):
    version_id: uuid.UUID
    query: str
    matches: List[DraftRetrievalMatchSchema]


class PublishVersionResponse(BaseModel):
    document_id: uuid.UUID
    document_title: str
    published_version_id: uuid.UUID
    published_version_number: int
    status: str
    retired_version_number: Optional[int] = None
    published_at: str
    message: str


class RollbackVersionResponse(BaseModel):
    document_id: uuid.UUID
    document_title: str
    restored_version_id: uuid.UUID
    restored_version_number: int
    retired_version_number: int
    status: str
    message: str


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    title: str
    version_id: uuid.UUID
    version_number: int
    status: str
    content_hash: str
    total_chunks: int
    total_tokens: int
    is_published: bool
    message: str
