from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IncidentRunbook(BaseModel):
    id: str
    title: str
    severity: str
    trigger_condition: str
    pillar: str
    diagnostic_steps: List[str]
    mitigation_steps: List[str]
    verification_check: str
    escalation_role: str


RUNBOOKS: Dict[str, IncidentRunbook] = {
    "sustained_error_rate": IncidentRunbook(
        id="sustained_error_rate",
        title="Sustained HTTP 5xx Error Rate Spike",
        severity="CRITICAL",
        trigger_condition="API error rate exceeds 1% over a 5-minute rolling window",
        pillar="Service Health",
        diagnostic_steps=[
            "1. Inspect recent error traces using GET /api/v1/ops/requests/{request_id} for failing request IDs.",
            "2. Check PostgreSQL connection pool utilization and query locks.",
            "3. Inspect structured logs for database connectivity or uncaught exception stack traces.",
            "4. Verify Redis connectivity and memory consumption.",
        ],
        mitigation_steps=[
            "1. If database pool is exhausted, recycle stale sessions or increase pool ceiling.",
            "2. If a specific bad payload caused cascading unhandled errors, deploy targeted validation patch.",
            "3. Restart worker or web container replicas gradually via rolling deploy.",
            "4. Engage secondary standby database if failover is required.",
        ],
        verification_check="Error rate drops below 0.1% for 15 consecutive minutes; GET /health returns 200 OK.",
        escalation_role="Lead Platform Engineer / SRE on-call",
    ),
    "high_ai_latency": IncidentRunbook(
        id="high_ai_latency",
        title="High AI Inference Latency or LLM Timeout",
        severity="HIGH",
        trigger_condition="Completed AI answer p95 latency exceeds 12 seconds or timeout rate > 2%",
        pillar="AI Quality",
        diagnostic_steps=[
            "1. Inspect GET /api/v1/ops/dashboard AI Quality metrics for recent latency and token consumption.",
            "2. Query GET /api/v1/ops/requests/{request_id} to examine whether delay is in vector retrieval or LLM generation.",
            "3. Check external LLM provider status page / API latency.",
            "4. Review average retrieved chunk count and prompt token sizes.",
        ],
        mitigation_steps=[
            "1. Temporarily reduce top_k retrieval chunks from 3 to 2 if prompt size is excessive.",
            "2. Switch LLM provider adapter to secondary standby endpoint or model (e.g. gpt-4o-mini fallback).",
            "3. Enable aggressive caching in Redis for repeat procedural inquiries.",
            "4. Check vector index performance in pgvector and rebuild IVFFlat/HNSW index if degraded.",
        ],
        verification_check="AI answer p95 latency returns below 12 seconds; retrieval hit rate stays above 85%.",
        escalation_role="AI / Machine Learning Engineer",
    ),
    "ingestion_backlog": IncidentRunbook(
        id="ingestion_backlog",
        title="Knowledge Ingestion Backlog or Publishing Failure",
        severity="MEDIUM",
        trigger_condition="Document ingestion to publish time exceeds 5 minutes or failed ingestion count > 0",
        pillar="Knowledge",
        diagnostic_steps=[
            "1. Inspect worker container logs for PDF parsing, text extraction, or embedding timeouts.",
            "2. Check Redis task queue depth for queued ingestion tasks.",
            "3. Verify that uploaded PDF format conforms to supported PDF 1.4 - 2.0 standards.",
            "4. Confirm that the atomic version switch transaction completed without lock contention.",
        ],
        mitigation_steps=[
            "1. Scale worker container count from 1 to 2 replicas to process pending queue backlog.",
            "2. Re-trigger failed document ingestion task manually via support console or worker queue.",
            "3. Roll back draft version to prior ACTIVE version if new chunk index has corrupted embeddings.",
        ],
        verification_check="Zero failed ingestion jobs in dead-letter queue; draft successfully transitions to ACTIVE.",
        escalation_role="Knowledge Operations Lead",
    ),
    "breached_case_sla": IncidentRunbook(
        id="breached_case_sla",
        title="Customer Support Case Age Breach / SLA Violation",
        severity="HIGH",
        trigger_condition="Active case age exceeds 48 hours without specialist triage or resolution",
        pillar="Customer Flow",
        diagnostic_steps=[
            "1. Query GET /api/v1/support/cases?status=NEW&status=TRIAGED to identify stagnant queue items.",
            "2. Filter by priority URGENT and HIGH to assess unassigned high-severity cases.",
            "3. Check if assigned specialist is inactive or overloaded.",
        ],
        mitigation_steps=[
            "1. Bulk reassign stagnant cases to available active support agents.",
            "2. Execute TriageCommand or RequestInfoCommand to advance case state from NEW to IN_REVIEW.",
            "3. Send automated reminder notification to customer if case is pending in WAITING status.",
        ],
        verification_check="No open cases exceed 48-hour SLA deadline; average resolution time decreases.",
        escalation_role="Support Operations Supervisor",
    ),
}


def get_all_runbooks() -> List[IncidentRunbook]:
    return list(RUNBOOKS.values())


def get_runbook(runbook_id: str) -> Optional[IncidentRunbook]:
    return RUNBOOKS.get(runbook_id)
