import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.cases.models import CasePriority, CaseStatus


class CitationSchema(BaseModel):
    document_title: str
    chunk_id: Optional[str] = None
    source_url: Optional[str] = None
    excerpt: Optional[str] = None


class ExtractedFactSchema(BaseModel):
    fact_key: str
    fact_value: str
    confidence: float = 1.0
    source: str = "AI_EXTRACTION"
    verified: bool = False


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Customer query or question")
    conversation_id: Optional[uuid.UUID] = Field(None, description="Optional existing conversation ID")
    channel: str = Field("web", description="Interaction channel (web, mobile, whatsapp)")
    full_name: Optional[str] = Field(None, description="Customer full name if known")
    phone_number: Optional[str] = Field(None, description="Customer phone number if known")


class QuestionResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    intent: str
    answer: str
    citations: List[CitationSchema] = Field(default_factory=list)
    prompt_case_creation: bool = False
    suggested_category: Optional[str] = None
    suggested_subject: Optional[str] = None
    extracted_facts: List[ExtractedFactSchema] = Field(default_factory=list)


class CreateCustomerCaseRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=255, description="Brief summary of the issue")
    description: Optional[str] = Field(None, description="Detailed problem description")
    category: str = Field("GENERAL_INQUIRY", description="Case category")
    priority: CasePriority = Field(CasePriority.NORMAL, description="Case priority")
    conversation_id: Optional[uuid.UUID] = Field(None, description="Existing conversation to link and pull extracted facts from")
    # Identity details (required if user is unauthenticated)
    full_name: Optional[str] = Field(None, description="Customer full name")
    phone_number: Optional[str] = Field(None, description="Customer phone number")
    email: Optional[str] = Field(None, description="Customer email address")
    nin_or_bvn: Optional[str] = Field(None, description="Customer NIN or BVN")
    metadata_json: Optional[Dict[str, Any]] = Field(default_factory=dict)
    additional_facts: Optional[List[ExtractedFactSchema]] = Field(default_factory=list)


class CustomerCaseResponse(BaseModel):
    id: uuid.UUID
    case_number: str
    status: CaseStatus
    priority: CasePriority
    category: str
    subject: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    extracted_facts: List[ExtractedFactSchema] = Field(default_factory=list)


class TimelineItemSchema(BaseModel):
    event_type: str
    description: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    actor_role: str
    timestamp: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


class MessageSchema(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: str
    content: str
    citations: List[Any] = Field(default_factory=list)
    attachments: List[Any] = Field(default_factory=list)
    created_at: datetime


class RequestedActionSchema(BaseModel):
    action_type: str
    reason: str
    requested_fields: Optional[Any] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    requested_at: Optional[str] = None


class CustomerCaseDetailResponse(BaseModel):
    id: uuid.UUID
    case_number: str
    status: CaseStatus
    priority: CasePriority
    category: str
    subject: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sla_deadline: Optional[datetime] = None
    requested_actions: List[RequestedActionSchema] = Field(default_factory=list)
    timeline: List[TimelineItemSchema] = Field(default_factory=list)
    messages: List[MessageSchema] = Field(default_factory=list)
    attachments: List[Any] = Field(default_factory=list)
    extracted_facts: List[ExtractedFactSchema] = Field(default_factory=list)


class CustomerMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Customer reply content")
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Optional attachment metadata")


class CustomerMessageResponse(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    case_id: uuid.UUID
    content: str
    sender_type: str
    created_at: datetime
    case_status: CaseStatus
    status_shifted_to_in_review: bool
