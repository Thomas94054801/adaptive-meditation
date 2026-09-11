"""Shared fixtures.

The suite runs against whatever ``TEST_DATABASE_URL`` names. With nothing set it
uses a temporary SQLite file so the domain and API tests run on a bare checkout;
CI and the local verification run point it at PostgreSQL 16, which is the
production dialect. Either way the schema is built by running the real Alembic
migration, so a migration that drifts from the models fails the suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.domain.practice.catalog import KnowledgeCatalog, load_catalog
from app.domain.recommendation.engine import RecommendationEngine
from app.main import create_app
from app.settings import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = BACKEND_ROOT.parent / "knowledge"


def running_on_postgres(url: str) -> bool:
    return url.startswith("postgresql")


@pytest.fixture(scope="session")
def catalog() -> KnowledgeCatalog:
    return load_catalog(KNOWLEDGE_DIR)


@pytest.fixture(scope="session")
def engine(catalog: KnowledgeCatalog) -> RecommendationEngine:
    return RecommendationEngine(catalog)


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    configured = os.environ.get("TEST_DATABASE_URL")
    if configured:
        return configured
    path = tmp_path_factory.mktemp("program001-db") / "program001.sqlite"
    return f"sqlite+pysqlite:///{path}"


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config, database_url: str) -> Iterator[str]:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield database_url
    command.downgrade(alembic_config, "base")


@pytest.fixture(scope="session")
def settings(migrated_database: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=migrated_database,
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
