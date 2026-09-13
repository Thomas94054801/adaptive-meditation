"""Per-run schema isolation — SDD ADR-004-06, Slice A.

The defect this closes cost time in Program002 and again in Program003: two
pytest sessions against one PostgreSQL database destroyed each other, because
the schema was dropped and recreated per session.

The acceptance gate is an external one — two complete suites running
concurrently — because a test cannot prove its own isolation from inside a
single run. What these tests cover is the machinery that makes that gate pass,
and the guard that keeps it out of production.
"""

from __future__ import annotations

import re
import time

import pytest
import sqlalchemy as sa

from app.persistence.schema_isolation import (
    STALE_AFTER_SECONDS,
    TEST_SCHEMA_PREFIX,
    UnsafeSchemaName,
    assert_safe_identifier,
    is_stale,
    is_test_schema,
    new_test_schema,
    schema_age_seconds,
)
from app.settings import Settings

from .conftest import running_on_postgres


def test_names_are_unique_per_invocation() -> None:
    names = {new_test_schema() for _ in range(500)}
    assert len(names) == 500


def test_names_are_unique_per_worker() -> None:
    run = "abcd1234"
    names = {new_test_schema(worker_id=w, run_id=run) for w in ("main", "gw0", "gw1", "gw2")}
    assert len(names) == 4


def test_names_fit_the_postgres_identifier_limit() -> None:
    name = new_test_schema(worker_id="gw15")
    assert len(name) <= 63


def test_names_carry_their_creation_time() -> None:
    """So a killed run can be swept later without a side table."""
    name = new_test_schema()
    age = schema_age_seconds(name)
    assert age is not None
    assert 0 <= age <= 5


def test_a_foreign_schema_has_no_age_and_is_never_stale() -> None:
    for foreign in ("public", "information_schema", "app_data", "testing"):
        assert schema_age_seconds(foreign) is None
        assert is_stale(foreign) is False


def test_only_old_schemas_are_stale() -> None:
    """Conservative on purpose.

    A schema younger than the TTL is never swept, so a long suite cannot have
    its schema dropped by a concurrently starting one.
    """
    fresh = new_test_schema()
    assert is_stale(fresh) is False
    assert is_stale(fresh, now=time.time() + STALE_AFTER_SECONDS - 60) is False
    assert is_stale(fresh, now=time.time() + STALE_AFTER_SECONDS + 60) is True


@pytest.mark.parametrize(
    "unsafe",
    [
        'test"; DROP SCHEMA public CASCADE; --',
        "test-schema",
        "test schema",
        "1test",
        "",
        "x" * 64,
        "test\nname",
    ],
)
def test_unsafe_identifiers_are_refused(unsafe: str) -> None:
    """Schema names cannot be bound as parameters, so this is the injection boundary."""
    with pytest.raises(UnsafeSchemaName):
        assert_safe_identifier(unsafe)


def test_generated_names_are_always_safe() -> None:
    for worker in ("main", "gw0", "weird-worker!", "gw10"):
        assert_safe_identifier(new_test_schema(worker_id=worker))


def test_test_schemas_are_recognisable() -> None:
    assert is_test_schema(new_test_schema())
    assert is_test_schema("public") is False


# --- the production guard -----------------------------------------------------


def test_production_refuses_a_test_schema() -> None:
    with pytest.raises(ValueError, match="test schema"):
        Settings(app_env="production", database_schema=new_test_schema())


def test_production_refuses_a_url_naming_a_test_schema() -> None:
    with pytest.raises(ValueError, match="search_path"):
        Settings(
            app_env="production",
            database_url=(
                "postgresql+psycopg://u@h/db?options=-csearch_path%3D"
                f"{TEST_SCHEMA_PREFIX}123_abcd1234_main"
            ),
        )


def test_non_production_environments_allow_a_test_schema() -> None:
    for env in ("development", "staging", "test"):
        assert Settings(app_env=env, database_schema=new_test_schema()).database_schema


def test_production_allows_an_ordinary_schema() -> None:
    assert Settings(app_env="production", database_schema="app").database_schema == "app"


# --- the live schema ----------------------------------------------------------


def test_this_run_owns_a_private_schema(test_schema: str | None, migrated_database: str) -> None:
    if not running_on_postgres(migrated_database):
        pytest.skip("PostgreSQL-only; schemas do not exist on SQLite")
    assert test_schema is not None
    assert re.match(rf"^{TEST_SCHEMA_PREFIX}\d+_[0-9a-f]{{8}}_\w+$", test_schema)


def test_the_tables_live_in_that_schema(
    settings: Settings, test_schema: str | None, migrated_database: str
) -> None:
    """Not in public — which is what keeps a second run from seeing them."""
    if not running_on_postgres(migrated_database):
        pytest.skip("PostgreSQL-only")
    from app.persistence.database import Database

    database = Database(settings)
    try:
        with database.session() as session:
            here = set(
                session.execute(
                    sa.text(
                        "select table_name from information_schema.tables "
                        "where table_schema = :s"
                    ),
                    {"s": test_schema},
                ).scalars()
            )
            assert {"sessions", "guest_profiles", "check_ins"} <= here
            assert "alembic_version" in here, "migration state must be schema-local too"
    finally:
        database.dispose()


def test_the_connection_resolves_to_that_schema(
    settings: Settings, test_schema: str | None, migrated_database: str
) -> None:
    if not running_on_postgres(migrated_database):
        pytest.skip("PostgreSQL-only")
    from app.persistence.database import Database

    database = Database(settings)
    try:
        with database.session() as session:
            assert session.execute(sa.text("select current_schema()")).scalar() == test_schema
    finally:
        database.dispose()


def test_a_second_schema_can_coexist(
    settings: Settings, test_schema: str | None, migrated_database: str
) -> None:
    """The property the concurrency gate proves, asserted in miniature.

    Creates a sibling schema, confirms both exist at once, and drops it. If two
    schemas could not coexist, the external two-suite proof could not pass.
    """
    if not running_on_postgres(migrated_database):
        pytest.skip("PostgreSQL-only")

    sibling = new_test_schema(worker_id="sibling")
    engine = sa.create_engine(migrated_database, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{sibling}"'))
            connection.commit()
            present = set(
                connection.execute(
                    sa.text(
                        "select schema_name from information_schema.schemata "
                        "where schema_name like :p"
                    ),
                    {"p": f"{TEST_SCHEMA_PREFIX}%"},
                ).scalars()
            )
            assert test_schema in present
            assert sibling in present
            connection.execute(sa.text(f'DROP SCHEMA "{sibling}" CASCADE'))
            connection.commit()
    finally:
        engine.dispose()
