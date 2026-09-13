"""Shared fixtures.

The suite runs against whatever ``TEST_DATABASE_URL`` names. With nothing set it
uses a temporary SQLite file so the domain and API tests run on a bare checkout;
CI and the local verification run point it at PostgreSQL 16, which is the
production dialect. Either way the schema is built by running the real Alembic
migration, so a migration that drifts from the models fails the suite.

**Isolation.** On PostgreSQL every invocation gets its own schema,
``test_<epoch>_<run_id>_<worker_id>``, created at session start and dropped at
the end. Two suites can therefore run against one server without touching each
other. Program002 and Program003 both lost time to the previous design, which
dropped and recreated a shared schema per session; a second run arriving
mid-suite deleted the first one's tables.

On SQLite each session already gets its own file, so nothing extra is needed.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.domain.practice.catalog import KnowledgeCatalog, load_catalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.recommendation.rulesets import V1RuleSet, V2RuleSet
from app.main import create_app
from app.persistence.schema_isolation import (
    TEST_SCHEMA_PREFIX,
    assert_safe_identifier,
    is_stale,
    new_test_schema,
)
from app.settings import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = BACKEND_ROOT.parent / "knowledge"


def running_on_postgres(url: str) -> bool:
    return url.startswith("postgresql")


@pytest.fixture(scope="session")
def catalog() -> KnowledgeCatalog:
    """Production knowledge (v2)."""
    return load_catalog(KNOWLEDGE_DIR, 2)


@pytest.fixture(scope="session")
def catalog_v1() -> KnowledgeCatalog:
    """Frozen Program001 knowledge, for replay."""
    return load_catalog(KNOWLEDGE_DIR, 1)


@pytest.fixture(scope="session")
def engine(catalog: KnowledgeCatalog) -> RecommendationEngine:
    """Production engine: rule set v2 on knowledge v2."""
    return RecommendationEngine(catalog, V2RuleSet())


@pytest.fixture(scope="session")
def engine_v1(catalog_v1: KnowledgeCatalog) -> RecommendationEngine:
    """Program001's engine, preserved so stored v1 records stay replayable."""
    return RecommendationEngine(catalog_v1, V1RuleSet())


@pytest.fixture
def guest_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def guest_headers(guest_id: str) -> dict[str, str]:
    return {"X-Guest-Id": guest_id}


@pytest.fixture(scope="session")
def worker_id() -> str:
    """The pytest-xdist worker, or "main" for a serial run."""
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory, worker_id: str) -> str:
    configured = os.environ.get("TEST_DATABASE_URL")
    if configured:
        return configured
    # A SQLite run is isolated by its own file; include the worker so xdist
    # workers do not share one either.
    path = tmp_path_factory.mktemp("program-db") / f"program_{worker_id}.sqlite"
    return f"sqlite+pysqlite:///{path}"


@pytest.fixture(scope="session")
def test_schema(database_url: str, worker_id: str) -> str | None:
    """The schema this invocation owns, or None on SQLite."""
    if not running_on_postgres(database_url):
        return None
    return new_test_schema(worker_id=worker_id)


@pytest.fixture(scope="session")
def alembic_config(database_url: str, test_schema: str | None) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    if test_schema:
        config.set_main_option("target_schema", test_schema)
    return config


@pytest.fixture(scope="session")
def migrated_database(
    alembic_config: Config, database_url: str, test_schema: str | None
) -> Iterator[str]:
    """Build the schema by running the real migrations, then drop it.

    Note what is *not* here any more: a ``downgrade base`` at the start. The
    schema is new, so there is nothing to tear down, and running a downgrade
    against a shared database was the mechanism by which two suites destroyed
    each other.
    """
    if test_schema:
        _sweep_stale_schemas(database_url)

    command.upgrade(alembic_config, "head")
    try:
        yield database_url
    finally:
        if test_schema:
            _drop_schema(database_url, test_schema)
        else:
            command.downgrade(alembic_config, "base")


def _admin_engine(database_url: str) -> Engine:
    """A connection with no search_path pinned, for DDL about schemas."""
    return create_engine(database_url, poolclass=NullPool)


def _drop_schema(database_url: str, schema: str) -> None:
    assert_safe_identifier(schema)
    engine = _admin_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.commit()
    finally:
        engine.dispose()


def _sweep_stale_schemas(database_url: str) -> None:
    """Drop test schemas left behind by killed runs.

    Conservative by design: only schemas older than the TTL are touched, so a
    long-running suite is never cleaned up by a concurrently starting one.
    """
    engine = _admin_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name LIKE :pattern"
                ),
                {"pattern": f"{TEST_SCHEMA_PREFIX}%"},
            ).scalars()
            stale = [name for name in rows if is_stale(name)]
            for name in stale:
                assert_safe_identifier(name)
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
            if stale:
                connection.commit()
    except SQLAlchemyError:
        # A sweep failure must never fail the suite: the run's own schema is
        # unique regardless, so stale debris is untidy rather than dangerous.
        pass
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def settings(migrated_database: str, test_schema: str | None) -> Settings:
    return Settings(
        app_env="test",
        database_url=migrated_database,
        database_schema=test_schema or "",
        knowledge_dir=KNOWLEDGE_DIR,
        ai_provider="null",
        ai_api_key=None,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_check_in() -> dict[str, object]:
    return {
        "goal": "overthinking",
        "stress": 8,
        "energy": 5,
        "mental_activity": 9,
        "sleepiness": 2,
        "available_minutes": 10,
        "experience_level": "beginner",
    }
