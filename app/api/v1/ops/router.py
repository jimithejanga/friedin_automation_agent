import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.ops.schemas import (
    AuditLogSearchResponse,
    DashboardMetricsResponse,
    RequestDiagnosisResponse,
    RunbookSchema,
)
from app.ops.runbooks import get_all_runbooks, get_runbook
from app.ops.service import OpsDashboardService
from app.platform.auth import AuthenticatedUser, Role, require_roles
from app.platform.database import get_db_session


router = APIRouter()

# Restrict operations surface to authorized staff roles
require_ops_staff = require_roles(Role.ADMIN, Role.SUPERVISOR, Role.AUDITOR)


@router.get(
    "/dashboard",
    response_model=DashboardMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get 4-pillar operational metrics (Service Health, Customer Flow, AI Quality, Knowledge)",
)
async def get_dashboard_metrics(
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_ops_staff),
) -> DashboardMetricsResponse:
    """Retrieve operational dashboard data across Service Health, Customer Flow,
    AI Quality, and Knowledge Base pillars.
    """
    metrics = await OpsDashboardService.get_dashboard_metrics(session)
    return DashboardMetricsResponse(**metrics)


@router.get(
    "/audit-logs",
    response_model=AuditLogSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search PII-masked append-only audit events",
)
async def search_audit_logs(
    request_id: Optional[str] = Query(None, description="Filter by request ID"),
    actor_id: Optional[uuid.UUID] = Query(None, description="Filter by actor user ID"),
    actor_role: Optional[str] = Query(None, description="Filter by actor role (customer, support, admin, auditor)"),
    action: Optional[str] = Query(None, description="Filter by action name pattern"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (case, document, ai_run, person)"),
    limit: int = Query(50, ge=1, le=200, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_ops_staff),
) -> AuditLogSearchResponse:
    """Search durable audit logs with guaranteed PII masking for compliance and operational auditing."""
    result = await OpsDashboardService.search_audit_logs(
        session=session,
        request_id=request_id,
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )
    return AuditLogSearchResponse(**result)


@router.get(
    "/requests/{request_id}",
    response_model=RequestDiagnosisResponse,
    status_code=status.HTTP_200_OK,
    summary="Diagnose request by Request ID (Phase 6 Exit Check)",
)
async def diagnose_request(
    request_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(require_ops_staff),
) -> RequestDiagnosisResponse:
    """Phase 6 Exit Check: Locate a request by its Request ID and view the exact error trace,
    AI execution parameters, and database mutations.
    """
    diagnosis = await OpsDashboardService.diagnose_request(session, request_id)
    return RequestDiagnosisResponse(**diagnosis)


@router.get(
    "/runbooks",
    response_model=List[RunbookSchema],
    status_code=status.HTTP_200_OK,
    summary="List operational incident diagnosis and recovery runbooks",
)
async def list_runbooks(
    current_user: AuthenticatedUser = Depends(require_ops_staff),
) -> List[RunbookSchema]:
    """Retrieve all standard operating procedure runbooks for system alerts and incidents."""
    return [RunbookSchema(**r.model_dump()) for r in get_all_runbooks()]


@router.get(
    "/runbooks/{runbook_id}",
    response_model=RunbookSchema,
    status_code=status.HTTP_200_OK,
    summary="Get detailed incident response runbook by ID",
)
async def get_runbook_detail(
    runbook_id: str,
    current_user: AuthenticatedUser = Depends(require_ops_staff),
) -> RunbookSchema:
    """Retrieve specific diagnostic checklist and recovery instructions for an incident."""
    runbook = get_runbook(runbook_id)
    if not runbook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Runbook '{runbook_id}' not found",
        )
    return RunbookSchema(**runbook.model_dump())
