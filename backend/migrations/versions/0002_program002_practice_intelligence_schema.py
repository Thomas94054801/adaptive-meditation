"""Program002 schema: guest ownership, recommendation provenance, candidates,
outcome evidence and experiment assignments.

Guest data becomes server-side, so every table that can hold it hangs off
``guest_profiles`` with ON DELETE CASCADE. That is what makes DELETE /v1/me/data
a single delete rather than a list of statements someone has to remember to
extend when a table is added.

Program001 rows are not rewritten. Every new column is nullable, so an existing
recommendation keeps exactly the shape it was served with and stays replayable.

Portability: the ALTERs run inside ``batch_alter_table`` so the same migration
applies on PostgreSQL (plain ALTER) and on the SQLite fallback the test suite
uses when no server is available (table recreate).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCALE_AFTER_COLUMNS = ("stress_after", "energy_after", "mental_activity_after", "sleepiness_after")


def upgrade() -> None:
    op.create_table(
        "guest_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_guest_profiles"),
    )

    op.create_table(
        "recommendation_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("practice_id", sa.String(length=32), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column(
            "reason_codes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_candidates_score"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_candidates_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendation_candidates"),
        sa.UniqueConstraint("session_id", "practice_id", name="uq_candidates_session_practice"),
    )
    op.create_index(
        op.f("ix_recommendation_candidates_session_id"),
        "recommendation_candidates",
        ["session_id"],
    )

    op.create_table(
        "experiment_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guest_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=32), nullable=False),
        sa.Column("assignment_key", sa.String(length=64), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guest_profiles.id"],
            name="fk_assignment_guest",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_experiment_assignments"),
        sa.UniqueConstraint("guest_id", "experiment_id", name="uq_assignment_guest_experiment"),
    )
    op.create_index(
        op.f("ix_experiment_assignments_guest_id"), "experiment_assignments", ["guest_id"]
    )

    with op.batch_alter_table("check_ins") as batch:
        batch.add_column(sa.Column("guest_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_check_ins_guest", "guest_profiles", ["guest_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index(op.f("ix_check_ins_guest_id"), "check_ins", ["guest_id"])

    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("guest_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("engine_version", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("rule_set_version", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("state_fingerprint", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_sessions_guest", "guest_profiles", ["guest_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index(op.f("ix_sessions_guest_id"), "sessions", ["guest_id"])
    op.create_index(op.f("ix_sessions_rule_set_version"), "sessions", ["rule_set_version"])
    op.create_index(op.f("ix_sessions_state_fingerprint"), "sessions", ["state_fingerprint"])

    with op.batch_alter_table("session_feedback") as batch:
        for column in SCALE_AFTER_COLUMNS:
            batch.add_column(sa.Column(column, sa.SmallInteger(), nullable=True))
        batch.add_column(sa.Column("completion_ratio", sa.Float(), nullable=True))
        batch.add_column(sa.Column("primary_measure", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("primary_delta", sa.SmallInteger(), nullable=True))
        batch.add_column(sa.Column("secondary_measure", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("secondary_delta", sa.SmallInteger(), nullable=True))
        batch.add_column(sa.Column("outcome_score", sa.SmallInteger(), nullable=True))
        for column in SCALE_AFTER_COLUMNS:
            # The API bounds, mirrored in the schema, as in migration 0001.
            batch.create_check_constraint(
                f"ck_session_feedback_{column}_range", f"{column} >= 0 AND {column} <= 10"
            )
        batch.create_check_constraint(
            "ck_session_feedback_completion_ratio",
            "completion_ratio IS NULL OR (completion_ratio >= 0 AND completion_ratio <= 1)",
        )


def downgrade() -> None:
    with op.batch_alter_table("session_feedback") as batch:
        batch.drop_constraint("ck_session_feedback_completion_ratio", type_="check")
        for column in SCALE_AFTER_COLUMNS:
            batch.drop_constraint(f"ck_session_feedback_{column}_range", type_="check")
        batch.drop_column("outcome_score")
        batch.drop_column("secondary_delta")
        batch.drop_column("secondary_measure")
        batch.drop_column("primary_delta")
        batch.drop_column("primary_measure")
        batch.drop_column("completion_ratio")
        for column in reversed(SCALE_AFTER_COLUMNS):
            batch.drop_column(column)

    op.drop_index(op.f("ix_sessions_state_fingerprint"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_rule_set_version"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_guest_id"), table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("fk_sessions_guest", type_="foreignkey")
        batch.drop_column("state_fingerprint")
        batch.drop_column("rule_set_version")
        batch.drop_column("engine_version")
        batch.drop_column("guest_id")

    op.drop_index(op.f("ix_check_ins_guest_id"), table_name="check_ins")
    with op.batch_alter_table("check_ins") as batch:
        batch.drop_constraint("fk_check_ins_guest", type_="foreignkey")
        batch.drop_column("guest_id")

    op.drop_index(op.f("ix_experiment_assignments_guest_id"), table_name="experiment_assignments")
    op.drop_table("experiment_assignments")
    op.drop_index(
        op.f("ix_recommendation_candidates_session_id"), table_name="recommendation_candidates"
    )
    op.drop_table("recommendation_candidates")
    op.drop_table("guest_profiles")
