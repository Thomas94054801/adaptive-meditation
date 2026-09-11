"""Database engine and session factory.

The engine is built lazily. ``/healthz`` and ``/v1/recommendations`` must answer
without a reachable database, so nothing here runs at import time.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.settings import Settings


def build_engine(settings: Settings) -> Engine:
    url = settings.database_url
    if url.startswith("sqlite"):
        # Used only by the test suite when no PostgreSQL server is available.
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if ":memory:" in url else None,
        )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


class Database:
    """Owns one engine and its session factory for the process lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._engine = build_engine(settings)
        self._session_factory = sessionmaker(
            bind=self._engine, autoflush=False, expire_on_commit=False
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self._engine.dispose()
