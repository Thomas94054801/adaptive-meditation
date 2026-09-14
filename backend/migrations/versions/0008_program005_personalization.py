"""Program005: personalization provenance and the familiarity index.

Additive. ``sessions.personalization`` is nullable, so every existing row
reads as "not personalized" and nothing is backfilled. The index covers the
familiarity count's predicate exactly - guest, status and the practice
inside the recommendation JSON - because a LIMIT bounds what a count returns,
not what a scan reads, and a guest with a long history of other practices
would otherwise pay for every row of it on each session create. The
expression form is what PostgreSQL matches at plan time; SQLite (the portable
test path) accepts the same ``->>`` syntax since 3.38.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14 09:40:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("sessions", sa.Column("personalization", JSON_VARIANT, nullable=True))
    op.create_index(
        "ix_sessions_familiarity",
        "sessions",
        ["guest_id", "status", sa.text("(recommendation ->> 'practice_id')")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_familiarity", table_name="sessions")
    op.drop_column("sessions", "personalization")
