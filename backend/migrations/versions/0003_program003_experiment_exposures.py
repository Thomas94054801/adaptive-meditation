"""Program003: experiment exposures.

Exposure is recorded separately from assignment. Being assigned to a variant is
not the same as having seen it, and counting assignment as exposure would
inflate every denominator the experiment exists to measure.

The unique constraint on (guest_id, experiment_id, context) is the exposure
semantics in the schema: one exposure per context, so re-opening a screen does
not double-count.


Revision ID: 0003
Revises: 0002
Create Date: 2026-09-11 16:32:02.142114+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_exposures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guest_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=32), nullable=False),
        sa.Column("context", sa.String(length=64), nullable=False),
        sa.Column(
            "exposed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["guest_id"], ["guest_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guest_id", "experiment_id", "context", name="uq_exposure_guest_experiment_context"
        ),
    )
    op.create_index(
        op.f("ix_experiment_exposures_guest_id"), "experiment_exposures", ["guest_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_experiment_exposures_guest_id"), table_name="experiment_exposures")
    op.drop_table("experiment_exposures")
