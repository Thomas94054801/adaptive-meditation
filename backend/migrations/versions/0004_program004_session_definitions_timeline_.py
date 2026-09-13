"""Program004: frozen session definitions, typed plan and the append-only event journal.

Three facts this schema records that the previous one could not:

- which exact words a session used, so a completed session stays interpretable
  after the knowledge files move on (``session_definitions``, referenced with
  ON DELETE RESTRICT because product content must outlive any one session);
- the typed plan and its hash, so a run is reproducible;
- where playback actually got to, segment by segment (``session_events``),
  because "they abandoned it" cannot be derived from a status column.

``session_definitions`` is deliberately **not** guest-linked. It is the
product's own content; deleting a guest must not delete it.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

RUN_STATES = (
    "created",
    "preparing",
    "ready",
    "playing",
    "paused",
    "completed",
    "abandoned",
    "failed",
)


def upgrade() -> None:
    op.create_table(
        "session_definitions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("practice_id", sa.String(length=32), nullable=False),
        sa.Column("protocol_id", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("content", JSON_VARIANT, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_definitions"),
    )
    op.create_index(
        op.f("ix_session_definitions_practice_id"), "session_definitions", ["practice_id"]
    )

    op.create_table(
        "session_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("segment_id", sa.String(length=64), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=True),
        sa.Column("detail", JSON_VARIANT, nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_session_events_sequence"),
        sa.CheckConstraint("elapsed_ms >= 0", name="ck_session_events_elapsed"),
        # Spelled out rather than imported, so a later rename of the Python
        # tuple cannot silently change what an old database accepts.
        sa.CheckConstraint(
            "event_type IN ("
            "'session_created', 'session_prepared', 'session_started', "
            "'segment_started', 'segment_completed', 'playback_paused', "
            "'playback_resumed', 'playback_interrupted', "
            "'playback_focus_regained', 'route_changed', 'session_completed', "
            "'session_abandoned', 'render_cache_hit', 'render_cache_miss', "
            "'render_failure', 'timeline_compressed', "
            "'timeline_drift_exceeded', 'silent_mode_used', "
            "'timeline_extended', 'playback_failed'"
            ")",
            name="ck_session_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_session_events_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_events"),
        # Makes a retried event request idempotent rather than duplicating.
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_events_sequence"),
    )
    op.create_index(op.f("ix_session_events_session_id"), "session_events", ["session_id"])
    op.create_index(op.f("ix_session_events_command_id"), "session_events", ["command_id"])

    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("plan_v2", JSON_VARIANT, nullable=True))
        batch.add_column(sa.Column("plan_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("definition_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("run_state", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("last_segment_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(
            sa.Column("command_sequence", sa.Integer(), server_default="0", nullable=False)
        )
        # RESTRICT, not CASCADE: product content must outlive a session that used it.
        batch.create_foreign_key(
            "fk_sessions_definition",
            "session_definitions",
            ["definition_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        states = ", ".join(f"'{state}'" for state in RUN_STATES)
        batch.create_check_constraint(
            "ck_sessions_run_state", f"run_state IS NULL OR run_state IN ({states})"
        )
    op.create_index(op.f("ix_sessions_plan_hash"), "sessions", ["plan_hash"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sessions_plan_hash"), table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("ck_sessions_run_state", type_="check")
        batch.drop_constraint("fk_sessions_definition", type_="foreignkey")
        batch.drop_column("command_sequence")
        batch.drop_column("elapsed_ms")
        batch.drop_column("last_segment_id")
        batch.drop_column("run_state")
        batch.drop_column("definition_id")
        batch.drop_column("plan_hash")
        batch.drop_column("plan_v2")

    op.drop_index(op.f("ix_session_events_command_id"), table_name="session_events")
    op.drop_index(op.f("ix_session_events_session_id"), table_name="session_events")
    op.drop_table("session_events")
    op.drop_index(op.f("ix_session_definitions_practice_id"), table_name="session_definitions")
    op.drop_table("session_definitions")
