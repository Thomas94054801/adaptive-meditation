"""Persistence tests.

The schema under test is the one the Alembic migration produced (see conftest),
so these also prove the migration is usable, not merely present.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.orm import Session as OrmSession

from app.domain.recommendation.engine import RecommendationEngine
from app.domain.session.service import recommend_and_plan
from app.domain.state.models import CheckIn
from app.persistence import models
from app.persistence.database import Database
from app.persistence.repositories import CheckInRepository, SessionRepository
from app.settings import Settings

from .conftest import running_on_postgres


def engine_for(database_url: str, schema: str | None) -> sa.Engine:
    """An engine pinned to the run's schema.

    A bare create_engine would resolve to ``public`` and see an empty database,
    because this run's tables live in its own schema.
    """
    connect_args = (
        {"options": f"-csearch_path={schema}"}
        if schema and database_url.startswith("postgresql")
        else {}
    )
    return sa.create_engine(database_url, connect_args=connect_args)


CHECK_IN = CheckIn.model_validate(
    {
        "goal": "sleep",
        "stress": 6,
        "energy": 3,
        "mental_activity": 8,
        "sleepiness": 7,
        "available_minutes": 15,
        "experience_level": "beginner",
    }
)


@pytest.fixture
def database(settings: Settings) -> Database:
    return Database(settings)


def test_migration_leaves_no_pending_schema_difference(
    alembic_config: Config, migrated_database: str, test_schema: str | None
) -> None:
    """A model changed without a migration fails here rather than in production."""
    engine = engine_for(migrated_database, test_schema)
    with engine.connect() as connection:
        # The connection's search_path already resolves to the run's schema, so
        # alembic_version reflects as unqualified and needs no schema opt.
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, models.Base.metadata)
    engine.dispose()
    assert diff == [], f"models and migrations disagree: {diff}"


def test_migration_is_reversible(
    alembic_config: Config, migrated_database: str, test_schema: str | None
) -> None:
    command.downgrade(alembic_config, "base")
    engine = engine_for(migrated_database, test_schema)
    inspector = sa.inspect(engine)
    assert "check_ins" not in inspector.get_table_names(schema=test_schema)
    engine.dispose()
    command.upgrade(alembic_config, "head")


def test_round_trip_through_the_repositories(
    database: Database, engine: RecommendationEngine
) -> None:
    recommendation, plan = recommend_and_plan(engine, CHECK_IN)
    with database.session() as session:
        check_in_row = CheckInRepository(session).create(CHECK_IN)
        session_row = SessionRepository(session).create(
            check_in_id=check_in_row.id, recommendation=recommendation, plan=plan
        )
        session_id = session_row.id

    with database.session() as session:
        sessions = SessionRepository(session)
        stored = sessions.get(session_id)
        assert stored is not None
        assert stored.status == "created"
        assert stored.user_id is None
        assert stored.recommendation["practice_id"] == "body_awareness"
        assert stored.plan["total_seconds"] == 600
        assert len(stored.plan["stages"]) == len(plan.stages)


def test_check_in_row_round_trips_back_to_the_domain_model(database: Database) -> None:
    with database.session() as session:
        row = CheckInRepository(session).create(CHECK_IN)
        assert CheckInRepository.to_domain(row) == CHECK_IN


def test_status_transitions(database: Database, engine: RecommendationEngine) -> None:
    recommendation, plan = recommend_and_plan(engine, CHECK_IN)
    with database.session() as session:
        repo = SessionRepository(session)
        check_in_row = CheckInRepository(session).create(CHECK_IN)
        row = repo.create(check_in_id=check_in_row.id, recommendation=recommendation, plan=plan)
        assert row.status == "created"
        repo.mark_started(row)
        assert row.status == "started" and row.started_at is not None
        repo.finish(row, completed=True)
        assert row.status == "completed" and row.completed_at is not None


def test_abandoned_session_still_records_a_start_time(
    database: Database, engine: RecommendationEngine
) -> None:
    recommendation, plan = recommend_and_plan(engine, CHECK_IN)
    with database.session() as session:
        repo = SessionRepository(session)
        check_in_row = CheckInRepository(session).create(CHECK_IN)
        row = repo.create(check_in_id=check_in_row.id, recommendation=recommendation, plan=plan)
        repo.finish(row, completed=False)
        assert row.status == "abandoned"
        assert row.started_at is not None


def test_feedback_is_upserted_not_duplicated(
    database: Database, engine: RecommendationEngine
) -> None:
    recommendation, plan = recommend_and_plan(engine, CHECK_IN)
    with database.session() as session:
        repo = SessionRepository(session)
        check_in_row = CheckInRepository(session).create(CHECK_IN)
        row = repo.create(check_in_id=check_in_row.id, recommendation=recommendation, plan=plan)
        session_id = row.id
        repo.upsert_feedback(
            session_id=session_id,
            before_score=7,
            after_score=4,
            helpfulness=4,
            completed=True,
            notes=None,
        )
        repo.upsert_feedback(
            session_id=session_id,
            before_score=7,
            after_score=2,
            helpfulness=5,
            completed=True,
            notes="quieter",
        )

    with database.session() as session:
        stored = SessionRepository(session).get_feedback(session_id)
        assert stored is not None
        assert stored.after_score == 2
        assert stored.notes == "quieter"
        count = session.execute(
            sa.select(sa.func.count()).select_from(models.SessionFeedback)
        ).scalar_one()
        assert count >= 1


def test_out_of_range_value_is_refused_by_the_database(
    database: Database, migrated_database: str
) -> None:
    """The 0..10 bound is enforced in the schema, not only by Pydantic."""
    with pytest.raises(sa.exc.IntegrityError), database.session() as session:
        session.execute(
            sa.insert(models.CheckIn).values(
                id=uuid.uuid4(),
                goal="stress",
                stress=42,
                energy=5,
                mental_activity=5,
                sleepiness=5,
                available_minutes=10,
                experience_level="beginner",
            )
        )


def test_production_dialect_uses_jsonb(migrated_database: str, test_schema: str | None) -> None:
    if not running_on_postgres(migrated_database):
        pytest.skip("PostgreSQL-only assertion; set TEST_DATABASE_URL to run it")
    engine = engine_for(migrated_database, test_schema)
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "select column_name, data_type from information_schema.columns "
                "where table_name = 'sessions' and table_schema = :schema "
                "and column_name in ('recommendation', 'plan')"
            ),
            {"schema": test_schema or "public"},
        ).all()
    engine.dispose()
    assert {row[1] for row in rows} == {"jsonb"}


def test_timestamps_are_timezone_aware(database: Database) -> None:
    with database.session() as session:
        row = CheckInRepository(session).create(CHECK_IN)
        assert row.created_at.tzinfo is not None


def test_orm_session_type_is_the_sqlalchemy_one(database: Database) -> None:
    with database.session() as session:
        assert isinstance(session, OrmSession)
