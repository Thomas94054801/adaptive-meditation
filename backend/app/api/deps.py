"""Request-scoped dependencies.

The knowledge catalog and the recommendation engine are process-wide and
immutable; the database session is per request and always closed.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session as OrmSession

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.settings import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> RecommendationEngine:
    engine: RecommendationEngine = request.app.state.recommendation_engine
    return engine


def get_catalog(request: Request) -> KnowledgeCatalog:
    return get_engine(request).catalog


def get_db_session(request: Request) -> Iterator[OrmSession]:
    database = request.app.state.database
    with database.session() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[RecommendationEngine, Depends(get_engine)]
CatalogDep = Annotated[KnowledgeCatalog, Depends(get_catalog)]
DbSessionDep = Annotated[OrmSession, Depends(get_db_session)]
