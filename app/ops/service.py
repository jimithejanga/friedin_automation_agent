import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIRun
from app.cases.models import Case, CaseEvent, CaseStatus, Message, MessageSenderType
from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.platform.audit import DbAuditEvent, mask_pii


# Application startup timestamp for uptime tracking
STARTUP_TIME = time.time()


class OpsDashboardService:
    """Aggregates operational metrics across the 4 pillars, searches audit logs,
    and performs deep request diagnosis.
    """

    @classmethod
    async def get_service_health(cls, session: AsyncSession) -> Dict[str, Any]:
        """Pillar 1: Service Health - availability, error rates, latencies, container uptime."""
        # 1. Database readiness check
        db_healthy = True
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            db_healthy = False

        # 2. Total requests & error metrics from audit events
        total_requests_stmt = select(func.count(DbAuditEvent.id))
        total_requests = (await session.execute(total_requests_stmt)).scalar() or 0

        # Estimate errors from audit events with failure or error action
        error_stmt = select(func.count(DbAuditEvent.id)).where(
            DbAuditEvent.action.ilike("%fail%") | DbAuditEvent.action.ilike("%error%")
        )
        error_count = (await session.execute(error_stmt)).scalar() or 0
        error_rate_pct = round((error_count / total_requests * 100) if total_requests > 0 else 0.0, 2)

        # 3. AI / API latencies
        ai_latencies_stmt = select(AIRun.latency_ms)
        ai_latencies = (await session.execute(ai_latencies_stmt)).scalars().all()
        if ai_latencies:
            p50_latency = float(np.percentile(ai_latencies, 50))
            p95_latency = float(np.percentile(ai_latencies, 95))
        else:
            p50_latency = 0.0
            p95_latency = 0.0

        uptime_seconds = round(time.time() - STARTUP_TIME, 1)

        return {
            "status": "HEALTHY" if db_healthy and error_rate_pct < 1.0 else "DEGRADED",
            "uptime_seconds": uptime_seconds,
            "database_ready": db_healthy,
            "total_requests": total_requests,
            "error_count": error_count,
            "error_rate_pct": error_rate_pct,
            "p50_latency_ms": round(p50_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
            "slo_availability_target": ">= 99.9%",
            "slo_met": error_rate_pct <= 0.1,
        }

    @classmethod
    async def get_customer_flow(cls, session: AsyncSession) -> Dict[str, Any]:
        """Pillar 2: Customer Flow - answers delivered, cases opened, resolution times, case age."""
        # Answers delivered (Assistant messages)
        answers_stmt = select(func.count(Message.id)).where(
            Message.sender_type == MessageSenderType.ASSISTANT
        )
        answers_delivered = (await session.execute(answers_stmt)).scalar() or 0

        # Cases counts
        total_cases_stmt = select(func.count(Case.id))
        total_cases = (await session.execute(total_cases_stmt)).scalar() or 0

        active_statuses = [CaseStatus.NEW, CaseStatus.TRIAGED, CaseStatus.WAITING, CaseStatus.IN_REVIEW]
        active_cases_stmt = select(func.count(Case.id)).where(Case.status.in_(active_statuses))
        active_cases = (await session.execute(active_cases_stmt)).scalar() or 0

        resolved_cases_stmt = select(func.count(Case.id)).where(
            Case.status.in_([CaseStatus.RESOLVED, CaseStatus.CLOSED])
        )
        resolved_cases = (await session.execute(resolved_cases_stmt)).scalar() or 0

        # Average case age for active cases
        cases_stmt = select(Case.created_at).where(Case.status.in_(active_statuses))
        active_case_dates = (await session.execute(cases_stmt)).scalars().all()
        now = datetime.now(timezone.utc)

        def _to_utc(dt: Any) -> datetime:
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        if active_case_dates:
            ages_in_hours = [(now - _to_utc(d)).total_seconds() / 3600.0 for d in active_case_dates]
            avg_case_age_hours = round(float(np.mean(ages_in_hours)), 1)
        else:
            avg_case_age_hours = 0.0

        # Resolution time for resolved cases
        res_stmt = select(Case.created_at, Case.resolved_at).where(Case.resolved_at.is_not(None))
        res_dates = (await session.execute(res_stmt)).all()
        if res_dates:
            res_times = [(_to_utc(r_at) - _to_utc(c_at)).total_seconds() / 3600.0 for c_at, r_at in res_dates]
            avg_resolution_hours = round(float(np.mean(res_times)), 1)
        else:
            avg_resolution_hours = 0.0

        return {
            "answers_delivered": answers_delivered,
            "cases_opened": total_cases,
            "active_cases": active_cases,
            "resolved_cases": resolved_cases,
            "avg_case_age_hours": avg_case_age_hours,
            "avg_resolution_time_hours": avg_resolution_hours,
            "slo_non_ai_latency_target": "< 500 ms",
        }

    @classmethod
    async def get_ai_quality(cls, session: AsyncSession) -> Dict[str, Any]:
        """Pillar 3: AI Quality - retrieval hit rate, fallback rate, token usage, latency."""
        runs_stmt = select(AIRun)
        runs = (await session.execute(runs_stmt)).scalars().all()
        total_runs = len(runs)

        if total_runs == 0:
            return {
                "total_ai_runs": 0,
                "retrieval_hit_rate_pct": 100.0,
                "fallback_rate_pct": 0.0,
                "guardrail_trigger_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "avg_ai_latency_ms": 0.0,
                "p95_ai_latency_ms": 0.0,
                "slo_answer_latency_target": "< 12 sec",
                "slo_met": True,
            }

        hits = sum(1 for r in runs if r.retrieved_chunks and len(r.retrieved_chunks) > 0)
        fallbacks = sum(1 for r in runs if r.fallback_triggered)
        guardrails = sum(1 for r in runs if r.guardrail_triggered)

        total_input = sum(r.input_tokens for r in runs)
        total_output = sum(r.output_tokens for r in runs)
        total_tokens = sum(r.total_tokens for r in runs)

        latencies = [r.latency_ms for r in runs]
        avg_latency = float(np.mean(latencies))
        p95_latency = float(np.percentile(latencies, 95))

        hit_rate_pct = round((hits / total_runs) * 100, 1)
        fallback_rate_pct = round((fallbacks / total_runs) * 100, 1)

        return {
            "total_ai_runs": total_runs,
            "retrieval_hit_rate_pct": hit_rate_pct,
            "fallback_rate_pct": fallback_rate_pct,
            "guardrail_trigger_count": guardrails,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "avg_ai_latency_ms": round(avg_latency, 2),
            "p95_ai_latency_ms": round(p95_latency, 2),
            "slo_answer_latency_target": "< 12 sec",
            "slo_met": (p95_latency / 1000.0) <= 12.0,
        }

    @classmethod
    async def get_knowledge_metrics(cls, session: AsyncSession) -> Dict[str, Any]:
        """Pillar 4: Knowledge Base - active/draft versions, chunks, publication age."""
        doc_stmt = select(func.count(Document.id))
        total_docs = (await session.execute(doc_stmt)).scalar() or 0

        active_ver_stmt = select(func.count(DocumentVersion.id)).where(
            DocumentVersion.status == DocumentVersionStatus.ACTIVE
        )
        active_versions = (await session.execute(active_ver_stmt)).scalar() or 0

        draft_ver_stmt = select(func.count(DocumentVersion.id)).where(
            DocumentVersion.status == DocumentVersionStatus.DRAFT
        )
        draft_versions = (await session.execute(draft_ver_stmt)).scalar() or 0

        retired_ver_stmt = select(func.count(DocumentVersion.id)).where(
            DocumentVersion.status == DocumentVersionStatus.RETIRED
        )
        retired_versions = (await session.execute(retired_ver_stmt)).scalar() or 0

        chunks_stmt = select(func.count(Chunk.id))
        total_chunks = (await session.execute(chunks_stmt)).scalar() or 0

        token_stmt = select(func.avg(Chunk.token_count))
        avg_tokens = (await session.execute(token_stmt)).scalar() or 0.0

        return {
            "total_documents": total_docs,
            "active_versions": active_versions,
            "draft_versions": draft_versions,
            "retired_versions": retired_versions,
            "total_chunks": total_chunks,
            "avg_chunk_tokens": round(float(avg_tokens), 1),
            "publishing_guarantee": "Atomic version switch: only active versions visible to customers",
            "slo_ingestion_target": "< 5 min",
        }

    @classmethod
    async def get_dashboard_metrics(cls, session: AsyncSession) -> Dict[str, Any]:
        """Consolidates all 4 pillars into a single operational dashboard payload."""
        health = await cls.get_service_health(session)
        customer_flow = await cls.get_customer_flow(session)
        ai_quality = await cls.get_ai_quality(session)
        knowledge = await cls.get_knowledge_metrics(session)

        return {
            "service_health": health,
            "customer_flow": customer_flow,
            "ai_quality": ai_quality,
            "knowledge": knowledge,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    async def search_audit_logs(
        cls,
        session: AsyncSession,
        request_id: Optional[str] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Search audit logs with PII masking and structured filtering."""
        query = select(DbAuditEvent)

        if request_id:
            query = query.where(DbAuditEvent.request_id == request_id)
        if actor_id:
            query = query.where(DbAuditEvent.actor_id == actor_id)
        if actor_role:
            query = query.where(DbAuditEvent.actor_role == actor_role)
        if action:
            query = query.where(DbAuditEvent.action.ilike(f"%{action}%"))
        if entity_type:
            query = query.where(DbAuditEvent.entity_type == entity_type)

        # Count total matches
        count_query = select(func.count()).select_from(query.subquery())
        total_count = (await session.execute(count_query)).scalar() or 0

        # Fetch page ordered by timestamp descending
        query = query.order_by(DbAuditEvent.timestamp.desc()).limit(limit).offset(offset)
        events = (await session.execute(query)).scalars().all()

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": str(e.id),
                    "request_id": e.request_id,
                    "actor_id": str(e.actor_id) if e.actor_id else None,
                    "actor_role": e.actor_role,
                    "action": e.action,
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "details": mask_pii(e.details),  # Guarantee masking in ops output
                    "ip_address": e.ip_address,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in events
            ],
        }

    @classmethod
    async def diagnose_request(cls, session: AsyncSession, request_id: str) -> Dict[str, Any]:
        """Phase 6 Exit Check: Given a Request ID, locate and chronologically assemble
        the exact database events, AI execution run, and error traces.
        """
        timeline: List[Dict[str, Any]] = []

        # 1. Audit events with this request_id
        audit_stmt = (
            select(DbAuditEvent)
            .where(DbAuditEvent.request_id == request_id)
            .order_by(DbAuditEvent.timestamp.asc())
        )
        audit_events = (await session.execute(audit_stmt)).scalars().all()
        for ae in audit_events:
            timeline.append({
                "source": "AUDIT_LOG",
                "timestamp": ae.timestamp.isoformat(),
                "action": ae.action,
                "actor_id": str(ae.actor_id) if ae.actor_id else None,
                "actor_role": ae.actor_role,
                "entity_type": ae.entity_type,
                "entity_id": ae.entity_id,
                "details": mask_pii(ae.details),
            })

        # 2. AI Runs with this request_id
        ai_stmt = select(AIRun).where(AIRun.request_id == request_id).order_by(AIRun.created_at.asc())
        ai_runs = (await session.execute(ai_stmt)).scalars().all()
        for ar in ai_runs:
            timeline.append({
                "source": "AI_INFERENCE_RUN",
                "timestamp": ar.created_at.isoformat(),
                "action": f"AI_INFERENCE_{ar.intent}",
                "model_name": ar.model_name,
                "prompt_template_version": ar.prompt_template_version,
                "query": ar.query_text,
                "answer": ar.answer_text,
                "latency_ms": ar.latency_ms,
                "token_counts": {
                    "input": ar.input_tokens,
                    "output": ar.output_tokens,
                    "total": ar.total_tokens,
                },
                "retrieved_chunk_count": len(ar.retrieved_chunks) if ar.retrieved_chunks else 0,
                "citations": ar.citations,
                "fallback_triggered": ar.fallback_triggered,
                "guardrail_triggered": ar.guardrail_triggered,
            })

        # 3. Case Events matching request_id in payload or CaseEvent records
        case_stmt = select(CaseEvent).order_by(CaseEvent.created_at.asc())
        all_case_events = (await session.execute(case_stmt)).scalars().all()
        for ce in all_case_events:
            payload = ce.payload or {}
            if payload.get("request_id") == request_id or ce.reason == request_id:
                timeline.append({
                    "source": "CASE_MUTATION",
                    "timestamp": ce.created_at.isoformat(),
                    "action": ce.event_type,
                    "case_id": str(ce.case_id),
                    "from_status": ce.from_status,
                    "to_status": ce.to_status,
                    "actor_role": ce.actor_role,
                    "command_name": ce.command_name,
                    "payload": mask_pii(ce.payload),
                })

        # Sort combined chronological timeline
        timeline.sort(key=lambda x: x["timestamp"])

        has_failure = any(
            "fail" in item.get("action", "").lower()
            or "error" in item.get("action", "").lower()
            or item.get("fallback_triggered", False)
            for item in timeline
        )

        return {
            "request_id": request_id,
            "events_count": len(timeline),
            "diagnosed_status": "FAILED_OR_DEGRADED" if has_failure else ("SUCCESS" if timeline else "NOT_FOUND"),
            "timeline": timeline,
            "has_error_or_fallback": has_failure,
            "diagnosed_at": datetime.now(timezone.utc).isoformat(),
        }
