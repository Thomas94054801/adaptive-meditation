"""Alembic environment.

The URL comes from application settings, which read it from the environment.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.persistence.models import Base
from app.persistence.schema_isolation import assert_safe_identifier
from app.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A caller (the test suite) may pin the URL explicitly; otherwise it comes
# from application settings, which read it from the environment.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Optional target schema. The test suite pins a unique one per run so two
# concurrent suites cannot share, create or drop each other's tables.
target_schema = config.get_main_option("target_schema", None) or None
if target_schema:
    assert_safe_identifier(target_schema)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=target_schema,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        in_schema = bool(target_schema) and connection.dialect.name == "postgresql"
        if in_schema:
            # Create and enter the schema before configuring, so both the tables
            # and alembic_version land inside it rather than in public. Without
            # this, two concurrent runs would share one alembic_version row and
            # fight over it.
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{target_schema}"'))
            connection.execute(text(f'SET search_path TO "{target_schema}"'))
            connection.commit()

        # No version_table_schema: the search_path above already places
        # alembic_version inside the schema. Qualifying it as well makes
        # reflection and comparison disagree about where it lives.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
