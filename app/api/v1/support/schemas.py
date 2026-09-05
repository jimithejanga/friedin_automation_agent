import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.cases.models import CasePriority, CaseStatus


class PersonCaseSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_number: str
    status: CaseStatus
    priority: CasePriority
    category: str
    subject: str
    created_at: datetime
    updated_at: datetime


class PersonSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone_number: str
    email: Optional[str] = None
    nin_or_bvn: Optional[str] = None
    total_cases_count: int = 0
    open_cases_count: int = 0
    cases: List[PersonCaseSummarySchema] = Field(default_factory=list)


class PersonSearchResponse(BaseModel):
    total: int
    people: List[PersonSummarySchema]


class SupportCaseSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_number: str
    person_id: uuid.UUID
    person_name: Optional[str] = None
    person_phone: Optional[str] = None
    status: CaseStatus
    priority: CasePriority
    category: str
    subject: str
    assigned_to: Optional[uuid.UUID] = None
    sla_deadline: Optional[datetime] = None
    is_sla_breached: bool = False
    created_at: datetime
    updated_at: datetime


class SupportCaseListResponse(BaseModel):
    total: int
    cases: List[SupportCaseSummarySchema]


class SupportTimelineItemSchema(BaseModel):
    id: uuid.UUID
    event_type: str
    description: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    command_name: Optional[str] = None
    actor_id: Optional[uuid.UUID] = None
    actor_role: str
    reason: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class SupportMessageSchema(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: str
    sender_id: Optional[uuid.UUID] = None
    content: str
    citations: List[Any] = Field(default_factory=list)
    attachments: List[Any] = Field(default_factory=list)
    created_at: datetime


class SupportExtractedFactSchema(BaseModel):
    id: uuid.UUID
    fact_key: str
    fact_value: str
    confidence: float
    source: str
    verified: bool


class SupportCaseDetailResponse(BaseModel):
    id: uuid.UUID
    case_number: str
    person_id: uuid.UUID
    person_name: Optional[str] = None
    person_phone: Optional[str] = None
    person_email: Optional[str] = None
    status: CaseStatus
    priority: CasePriority
    category: str
    subject: str
    description: Optional[str] = None
    assigned_to: Optional[uuid.UUID] = None
    sla_deadline: Optional[datetime] = None
    is_sla_breached: bool = False
    created_at: datetime
    updated_at: datetime
    timeline: List[SupportTimelineItemSchema] = Field(default_factory=list)
    messages: List[SupportMessageSchema] = Field(default_factory=list)
    extracted_facts: List[SupportExtractedFactSchema] = Field(default_factory=list)


# --- Command Schemas ---

class TriageCommandPayload(BaseModel):
    category: str = Field(..., min_length=2, description="Case category")
    priority: CasePriority = Field(default=CasePriority.NORMAL, description="Assigned priority")
    reason: str = Field(..., min_length=3, description="Triage notes or assignment rationale")


class AssignCommandPayload(BaseModel):
    assignee_id: uuid.UUID = Field(..., description="UUID of support specialist assigned")
    reason: str = Field(..., min_length=3, description="Assignment reason")


class RequestInfoCommandPayload(BaseModel):
    requested_items: List[str] = Field(..., min_length=1, description="Requested documents or facts from customer")
    reason: str = Field(..., min_length=3, description="Reason information is requested")


class ResolveCommandPayload(BaseModel):
    resolution_summary: str = Field(..., min_length=5, description="Summary of resolution reached")
    reason: str = Field(..., min_length=3, description="Resolution confirmation reason")


class ReopenCommandPayload(BaseModel):
    reason: str = Field(..., min_length=5, description="Justification for reopening case")


class CloseCommandPayload(BaseModel):
    reason: str = Field(..., min_length=3, description="Closing confirmation notes")


class CommandExecutionResponse(BaseModel):
    case_id: uuid.UUID
    case_number: str
    command_name: str
    from_status: str
    to_status: str
    actor_id: Optional[uuid.UUID] = None
    actor_role: str
    executed_at: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


# --- Internal Staff Notes ---

class RecordInternalNoteRequest(BaseModel):
    note: str = Field(..., min_length=1, description="Internal staff note content")
    decision: Optional[str] = Field(None, description="Optional administrative decision or outcome")
    reason: Optional[str] = Field(default="Internal staff note recorded")


class RecordInternalNoteResponse(BaseModel):
    case_id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    actor_id: Optional[uuid.UUID] = None
    actor_role: str
    note: str
    decision: Optional[str] = None
    created_at: datetime
