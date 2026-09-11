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


class GuestProfile(Base):
    """A guest identity.

    The id is a client-generated UUIDv4 and nothing else: no hardware
    fingerprint, no IMEI, no advertising identifier, no email. It exists so a
    guest can see their own history and delete it, which is the only reason
    server-side guest data is kept at all.
    """

    __tablename__ = "guest_profiles"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
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
    # v2: guest ownership, so a guest can list and delete their own data.
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("guest_profiles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    goal: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    stress: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    energy: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    mental_activity: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    sleepiness: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    available_minutes: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    experience_level: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
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
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("guest_profiles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    check_in_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("check_ins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation: Mapped[dict[str, object]] = mapped_column(JSONType, nullable=False)
    protocol_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    protocol_version: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)

    # v2 recommendation provenance, promoted out of the JSON blob so it can be
    # queried and compared without parsing every row.
    engine_version: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    rule_set_version: Mapped[str | None] = mapped_column(sa.String(8), nullable=True, index=True)
    state_fingerprint: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    plan: Mapped[dict[str, object]] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    check_in: Mapped[CheckIn] = relationship(back_populates="sessions")
    feedback: Mapped[SessionFeedback | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    candidates: Mapped[list[RecommendationCandidate]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionFeedback(Base):
    __tablename__ = "session_feedback"
    __table_args__ = (
        *_scale_constraints(
            "ck_session_feedback",
            "before_score",
            "after_score",
            "stress_after",
            "energy_after",
            "mental_activity_after",
            "sleepiness_after",
        ),
        sa.CheckConstraint(
            "completion_ratio IS NULL OR (completion_ratio >= 0 AND completion_ratio <= 1)",
            name="ck_session_feedback_completion_ratio",
        ),
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
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )

    # v2: the full after-state, so every goal-specific outcome measure can be
    # computed. Nullable because Program001 rows have only after_score.
    stress_after: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    energy_after: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    mental_activity_after: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    sleepiness_after: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    completion_ratio: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # Derived outcome evidence. Recomputable from the raw values above, which
    # are never overwritten; stored so the evaluator does not recompute per row.
    primary_measure: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    primary_delta: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    secondary_measure: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    secondary_delta: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    # product optimization metric only - not clinical, not diagnostic
    outcome_score: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    session: Mapped[Session] = relationship(back_populates="feedback")


class RecommendationCandidate(Base):
    """One scored candidate from the rule set, kept for offline evaluation.

    Memory/storage: bounded at one row per practice per session - seven in v2 -
    so the table grows linearly with sessions, not combinatorially.
    """

    __tablename__ = "recommendation_candidates"
    __table_args__ = (
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_candidates_score"),
        sa.UniqueConstraint("session_id", "practice_id", name="uq_candidates_session_practice"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    practice_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    rank: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    score: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONType, nullable=False)

    session: Mapped[Session] = relationship(back_populates="candidates")


class ExperimentExposure(Base):
    """A recorded instance of a variant actually being shown.

    Separate from assignment on purpose. Being assigned to a variant is not the
    same as having seen it, and counting assignment as exposure would inflate
    every denominator the experiment exists to measure.

    Exposure semantics: one row per (guest, experiment, context). The context is
    the session the explanation was shown for, so re-opening the same screen is
    the same exposure rather than a new one.
    """

    __tablename__ = "experiment_exposures"
    __table_args__ = (
        sa.UniqueConstraint(
            "guest_id", "experiment_id", "context", name="uq_exposure_guest_experiment_context"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    guest_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("guest_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    variant: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    context: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    exposed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )


class ExperimentAssignment(Base):
    """A guest's variant for one experiment. Deterministic, so it is a cache."""

    __tablename__ = "experiment_assignments"
    __table_args__ = (
        sa.UniqueConstraint("guest_id", "experiment_id", name="uq_assignment_guest_experiment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    guest_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("guest_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    variant: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    assignment_key: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )
