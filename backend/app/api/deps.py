"""Request-scoped dependencies.

The knowledge catalog and the recommendation engine are process-wide and
immutable; the database session is per request and always closed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from app.ai.providers.base import AIProvider
from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.persistence.database import Database
from app.settings import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> RecommendationEngine:
    engine: RecommendationEngine = request.app.state.recommendation_engine
    return engine


def get_catalog(request: Request) -> KnowledgeCatalog:
    return get_engine(request).catalog


def get_ai_provider(request: Request) -> AIProvider:
    """The presentation provider main.py built from settings; null by default.

    Program005 is the first production caller. Tests override this dependency
    with a stub; production never sees anything but what the registry resolves.
    """
    provider: AIProvider = request.app.state.ai_provider
    return provider


def get_db_session(request: Request) -> Iterator[OrmSession]:
    database = request.app.state.database
    with database.session() as session:
        yield session


def get_database(request: Request) -> Database:
    """The database object, without opening a session.

    For routes that only *sometimes* need one. Depending on ``get_db_session``
    acquires a pooled connection on every request, which is pure cost on the
    calls that never use it - it cost the recommendation endpoint 67% of its
    p95 before this existed.
    """
    database: Database = request.app.state.database
    return database


SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[RecommendationEngine, Depends(get_engine)]
CatalogDep = Annotated[KnowledgeCatalog, Depends(get_catalog)]
AIProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
DbSessionDep = Annotated[OrmSession, Depends(get_db_session)]
DatabaseDep = Annotated[Database, Depends(get_database)]


GUEST_HEADER = "X-Guest-Id"


def optional_guest_id(
    x_guest_id: Annotated[str | None, Header(alias=GUEST_HEADER)] = None,
) -> uuid.UUID | None:
    """The caller's guest identity, when it sent one.

    Guest-first means optional: a caller with no identity still gets a
    recommendation and a session, it just has no history to come back to.
    A malformed value is a 422 rather than a silently ignored header, because
    silently dropping it would strand that guest's data under an id nobody holds.
    """
    if x_guest_id is None:
        return None
    try:
        return uuid.UUID(x_guest_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_guest_id",
                "message": f"{GUEST_HEADER} must be a UUID.",
            },
        ) from None


def required_guest_id(
    guest_id: Annotated[uuid.UUID | None, Depends(optional_guest_id)],
) -> uuid.UUID:
    """For the routes that act on a specific guest's data."""
    if guest_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "guest_id_required",
                "message": f"This endpoint requires a {GUEST_HEADER} header.",
            },
        )
    return guest_id


OptionalGuestDep = Annotated[uuid.UUID | None, Depends(optional_guest_id)]
RequiredGuestDep = Annotated[uuid.UUID, Depends(required_guest_id)]
