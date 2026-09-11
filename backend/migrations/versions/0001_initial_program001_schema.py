"""Initial Program001 schema: check_ins, sessions, session_feedback.

Guest-first: every ``user_id`` is nullable and unpopulated in Program001.
The 0..10 and enum bounds from the API are mirrored as CHECK constraints so the
database rejects out-of-range values independently of the application.

Revision ID: 0001
Revises: 
Create Date: 2026-09-11 09:34:34.397545+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('check_ins',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('goal', sa.String(length=32), nullable=False),
    sa.Column('stress', sa.SmallInteger(), nullable=False),
    sa.Column('energy', sa.SmallInteger(), nullable=False),
    sa.Column('mental_activity', sa.SmallInteger(), nullable=False),
    sa.Column('sleepiness', sa.SmallInteger(), nullable=False),
    sa.Column('available_minutes', sa.SmallInteger(), nullable=False),
    sa.Column('experience_level', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('available_minutes IN (3, 5, 10, 15, 20)', name='ck_check_ins_available_minutes'),
    sa.CheckConstraint('energy >= 0 AND energy <= 10', name='ck_check_ins_energy_range'),
    sa.CheckConstraint('mental_activity >= 0 AND mental_activity <= 10', name='ck_check_ins_mental_activity_range'),
    sa.CheckConstraint('sleepiness >= 0 AND sleepiness <= 10', name='ck_check_ins_sleepiness_range'),
    sa.CheckConstraint('stress >= 0 AND stress <= 10', name='ck_check_ins_stress_range'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_check_ins_user_id'), 'check_ins', ['user_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('check_in_id', sa.Uuid(), nullable=False),
    sa.Column('recommendation', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('protocol_id', sa.String(length=64), nullable=False),
    sa.Column('protocol_version', sa.SmallInteger(), nullable=False),
    sa.Column('plan', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('created', 'started', 'completed', 'abandoned')", name='ck_sessions_status'),
    sa.ForeignKeyConstraint(['check_in_id'], ['check_ins.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_check_in_id'), 'sessions', ['check_in_id'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('session_feedback',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('before_score', sa.SmallInteger(), nullable=True),
    sa.Column('after_score', sa.SmallInteger(), nullable=False),
    sa.Column('helpfulness', sa.SmallInteger(), nullable=False),
    sa.Column('completed', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('after_score >= 0 AND after_score <= 10', name='ck_session_feedback_after_score_range'),
    sa.CheckConstraint('before_score >= 0 AND before_score <= 10', name='ck_session_feedback_before_score_range'),
    sa.CheckConstraint('helpfulness >= 1 AND helpfulness <= 5', name='ck_session_feedback_helpfulness'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id')
    )


def downgrade() -> None:
    op.drop_table('session_feedback')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_check_in_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_check_ins_user_id'), table_name='check_ins')
    op.drop_table('check_ins')
