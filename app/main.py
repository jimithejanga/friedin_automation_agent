from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import structlog

from app.api.v1.customer.router import router as customer_router
from app.api.v1.ops.router import router as ops_router
from app.api.v1.support.router import router as support_router
from app.config import get_settings
from app.platform.database import get_db_session
from app.platform.telemetry import TelemetryMiddleware, setup_telemetry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = structlog.get_logger("cmr.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown routines."""
    setup_telemetry()
    settings = get_settings()
    logger.info(
        "cmr_application_started",
        app_name=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        debug=settings.DEBUG,
    )
    yield
    logger.info("cmr_application_shutdown")


def create_app() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="CMR Specialist Automation Agent - High-traffic Case-Centric Support Product",
        lifespan=lifespan,
    )

    # Middleware Stack
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TelemetryMiddleware)

    # Core Health Route
    class HealthResponse(BaseModel):
        status: str
        app: str
        environment: str
        request_id: str | None = None

    @app.get("/health", response_model=HealthResponse, tags=["Observability"])
    async def health_check(request: Request) -> HealthResponse:
        request_id = getattr(request.state, "request_id", None)
        return HealthResponse(
            status="ok",
            app=settings.APP_NAME,
            environment=settings.ENVIRONMENT,
            request_id=request_id,
        )

    # Readiness Probe
    class ReadinessResponse(BaseModel):
        status: str
        database: str
        app: str
        request_id: str | None = None

    @app.get("/health/ready", response_model=ReadinessResponse, tags=["Observability"])
    async def readiness_probe(
        request: Request,
        session: AsyncSession = Depends(get_db_session),
    ) -> ReadinessResponse:
        request_id = getattr(request.state, "request_id", None)
        try:
            await session.execute(text("SELECT 1"))
            db_status = "ready"
        except Exception:
            db_status = "unreachable"

        return ReadinessResponse(
            status="ready" if db_status == "ready" else "degraded",
            database=db_status,
            app=settings.APP_NAME,
            request_id=request_id,
        )

    # Customer Surface Router
    app.include_router(
        customer_router,
        prefix="/api/v1/customer",
        tags=["Customer Surface"],
    )

    # Support Console Surface Router
    app.include_router(
        support_router,
        prefix="/api/v1/support",
        tags=["Support Console Surface"],
    )

    # Operations Dashboard Surface Router
    app.include_router(
        ops_router,
        prefix="/api/v1/ops",
        tags=["Operations Dashboard Surface"],
    )

    return app


app = create_app()

