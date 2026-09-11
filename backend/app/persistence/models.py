"""SQLAlchemy models for the Program001 vertical slice.

Design notes:

- UUID primary keys and timezone-aware UTC timestamps throughout.
- ``user_id`` is nullable everywhere and is never populated in Program001. Guest
  usage is the default path, not a degraded one, and no fake identity is minted
  to satisfy a non-null column.
- The recommendation and the rendered plan are stored as JSON on the session row.
  SDD section 8 asks for the simpler design absent a concrete query requirement,
  and Program001 has none.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on PostgreSQL (the production dialect); portable JSON elsewhere so the
# suite can run without a database server.
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

SESSION_STATUSES = ("created", "started", "completed", "abandoned")
NOTES_MAX_LENGTH = 1000


class Base(DeclarativeBase):
    pass


def _scale_constraints(prefix: str, *fields: str) -> tuple[sa.CheckConstraint, ...]:
    """Mirror the 0..10 API bounds in the database itself."""
    return tuple(
        sa.CheckConstraint(f"{field} >= 0 AND {field} <= 10", name=f"{prefix}_{field}_range")
        for field in fields
    )


class CheckIn(Base):
    __tablename__ = "check_ins"
    __table_args__ = (
        *_scale_constraints("ck_check_ins", "stress", "energy", "mental_activity", "sleepiness"),
        sa.CheckConstraint(
            "available_minutes IN (3, 5, 10, 15, 20)", name="ck_check_ins_available_minutes"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True, index=True)
    goal: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    stress: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    energy: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    mental_activity: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    sleepiness: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    available_minutes: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    experience_level: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    sessions: Mapped[list[Session]] = relationship(back_populates="check_in")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('created', 'started', 'completed', 'abandoned')",
            name="ck_sessions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True, index=True)
    check_in_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("check_ins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation: Mapped[dict[str, object]] = mapped_column(JSONType, nullable=False)
    protocol_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    protocol_version: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    plan: Mapped[dict[str, object]] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    check_in: Mapped[CheckIn] = relationship(back_populates="sessions")
    feedback: Mapped[SessionFeedback | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )


class SessionFeedback(Base):
    __tablename__ = "session_feedback"
    __table_args__ = (
        *_scale_constraints("ck_session_feedback", "before_score", "after_score"),
        sa.CheckConstraint(
            "helpfulness >= 1 AND helpfulness <= 5", name="ck_session_feedback_helpfulness"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    before_score: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    after_score: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    helpfulness: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    completed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.String(NOTES_MAX_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    session: Mapped[Session] = relationship(back_populates="feedback")
