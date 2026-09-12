"""Program004: content-addressed audio renders.

One row per distinct rendered utterance, keyed by the hash of its render inputs.
Deliberately not linked to a guest or a session: the table records which content
was rendered, never who heard it, which is what lets two people on one device
share a file without either learning anything about the other.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audio_renders",
        sa.Column("render_key", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("voice_id", sa.String(length=64), nullable=False),
        sa.Column("style", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("provider_version", sa.String(length=32), nullable=False),
        sa.Column("render_version", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("uri", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint("duration_ms > 0", name="ck_audio_renders_duration"),
        sa.CheckConstraint("byte_size >= 0", name="ck_audio_renders_size"),
        sa.PrimaryKeyConstraint("render_key", name="pk_audio_renders"),
    )
    op.create_index(op.f("ix_audio_renders_locale"), "audio_renders", ["locale"])
    op.create_index(op.f("ix_audio_renders_provider_id"), "audio_renders", ["provider_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audio_renders_provider_id"), table_name="audio_renders")
    op.drop_index(op.f("ix_audio_renders_locale"), table_name="audio_renders")
    op.drop_table("audio_renders")
