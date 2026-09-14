"""FastAPI application factory.

Modular monolith: one process, one deployable, module boundaries enforced by
imports rather than by network hops. SDD section 2.1 rules out the infrastructure
that would justify splitting it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.ai.providers.registry import build_ai_provider
from app.api.system import router as system_router
from app.api.v1.guest_routes import router as guest_router
from app.api.v1.routes import router as v1_router
from app.domain.practice.catalog import get_catalog
from app.domain.recommendation.engine import RecommendationEngine
from app.persistence.database import Database
from app.settings import Settings, get_settings

API_DESCRIPTION = (
    "Adaptive Meditation Program001 vertical slice: check-in, deterministic "
    "practice recommendation, session protocol and outcome feedback. "
    "Wellness product; it does not diagnose or treat any condition."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Knowledge is validated at startup: a malformed protocol file fails the
    # boot rather than the first user request.
    yield
    database: Database | None = getattr(app.state, "database", None)
    if database is not None:
        database.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )

    catalog = get_catalog(settings.knowledge_dir)
    app.state.settings = settings
    app.state.recommendation_engine = RecommendationEngine(catalog)
    # Program005: the presentation provider becomes reachable. With no
    # AI_PROVIDER/AI_API_KEY this is the null provider, which returns the
    # deterministic wording unchanged; an unknown name still fails loudly.
    app.state.ai_provider = build_ai_provider(settings)
    # Building the engine object does not open a connection; /healthz and
    # /v1/recommendations stay answerable with the database down.
    app.state.database = Database(settings)

    app.include_router(system_router)
    # Order matters: guest_router owns the literal /v1/sessions/history, and
    # v1_router owns /v1/sessions/{session_id}. FastAPI matches in registration
    # order, so the literal path must be registered first or "history" is read
    # as a session id. test_literal_session_paths_are_not_shadowed pins this.
    app.include_router(guest_router)
    app.include_router(v1_router)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'][1:])}: {error['msg']}"
                        for error in exc.errors()
                    )
                    or "Invalid request.",
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = {"error": detail}
        else:
            body = {"error": {"code": f"http_{exc.status_code}", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    return app


app = create_app()
