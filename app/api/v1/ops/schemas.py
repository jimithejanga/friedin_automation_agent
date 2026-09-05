import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ServiceHealthSchema(BaseModel):
    status: str
    uptime_seconds: float
    database_ready: bool
    total_requests: int
    error_count: int
    error_rate_pct: float
    p50_latency_ms: float
    p95_latency_ms: float
    slo_availability_target: str
    slo_met: bool


class CustomerFlowSchema(BaseModel):
    answers_delivered: int
    cases_opened: int
    active_cases: int
    resolved_cases: int
    avg_case_age_hours: float
    avg_resolution_time_hours: float
    slo_non_ai_latency_target: str


class AIQualitySchema(BaseModel):
    total_ai_runs: int
    retrieval_hit_rate_pct: float
    fallback_rate_pct: float
    guardrail_trigger_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    avg_ai_latency_ms: float
    p95_ai_latency_ms: float
    slo_answer_latency_target: str
    slo_met: bool


class KnowledgeMetricsSchema(BaseModel):
    total_documents: int
    active_versions: int
    draft_versions: int
    retired_versions: int
    total_chunks: int
    avg_chunk_tokens: float
    publishing_guarantee: str
    slo_ingestion_target: str


class DashboardMetricsResponse(BaseModel):
    service_health: ServiceHealthSchema
    customer_flow: CustomerFlowSchema
    ai_quality: AIQualitySchema
    knowledge: KnowledgeMetricsSchema
    timestamp: str


class AuditLogItemSchema(BaseModel):
    id: str
    request_id: Optional[str] = None
    actor_id: Optional[str] = None
    actor_role: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: Optional[str] = None
    timestamp: str


class AuditLogSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AuditLogItemSchema]


class TimelineEventSchema(BaseModel):
    source: str
    timestamp: str
    action: str
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    model_name: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    payload: Optional[Dict[str, Any]] = None
    token_counts: Optional[Dict[str, int]] = None
    citations: Optional[List[Any]] = None
    fallback_triggered: Optional[bool] = None
    guardrail_triggered: Optional[bool] = None


class RequestDiagnosisResponse(BaseModel):
    request_id: str
    events_count: int
    diagnosed_status: str
    timeline: List[Dict[str, Any]]
    has_error_or_fallback: bool
    diagnosed_at: str


class RunbookSchema(BaseModel):
    id: str
    title: str
    severity: str
    trigger_condition: str
    pillar: str
    diagnostic_steps: List[str]
    mitigation_steps: List[str]
    verification_check: str
    escalation_role: str
