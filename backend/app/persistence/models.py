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
        sa.CheckConstraint(
            "run_state IS NULL OR run_state IN ('created', 'preparing', 'ready', "
            "'playing', 'paused', 'completed', 'abandoned', 'failed')",
            name="ck_sessions_run_state",
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

    # Program004: the typed plan and the content it froze. plan_hash makes the
    # run reproducible; definition_id keeps the exact words addressable after
    # the knowledge files move on.
    plan_v2: Mapped[dict[str, object] | None] = mapped_column(JSONType, nullable=True)
    plan_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    definition_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("session_definitions.id", ondelete="RESTRICT"), nullable=True
    )
    run_state: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    # Program004R. Nullable throughout: a session created before resolutions
    # existed replays from its plan, which is what keeps history readable.
    resolution_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    audio_mode: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    # Why a run is paused. The accepted SDD modelled `interrupted` as its own
    # state; the only transition that distinguished it was auto-resume on focus
    # regain, which this product refuses. A reason is additive where a new
    # state would change a frozen check constraint and every historical replay.
    pause_reason: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    delivery_evidence_version: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    last_segment_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    command_sequence: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
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
    events: Mapped[list[SessionEvent]] = relationship(cascade="all, delete-orphan")


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


# Program004 playback states. "backgrounded" is deliberately absent: audio that
# stops when the screen locks is not a meditation app, so backgrounding is an
# environment event, not a playback state.
SESSION_RUN_STATES = (
    "created",
    "preparing",
    "ready",
    "playing",
    "paused",
    "completed",
    "abandoned",
    "failed",
)

# Section 17.1 of the SDD, verbatim, plus two the accepted SDD corrections
# require: timeline_extended records the case where elastic silence could not
# absorb a speech overrun, and playback_failed records the run state of the same
# name. Anything not in this tuple is refused by both the API and the database.
SESSION_EVENT_TYPES = (
    "session_created",
    "session_prepared",
    "session_started",
    "segment_started",
    "segment_completed",
    "playback_paused",
    "playback_resumed",
    "playback_interrupted",
    "playback_focus_regained",
    "route_changed",
    "session_completed",
    "session_abandoned",
    "render_cache_hit",
    "render_cache_miss",
    "render_failure",
    "timeline_compressed",
    "timeline_drift_exceeded",
    "silent_mode_used",
    "timeline_extended",
    "playback_failed",
)


class SessionDefinitionRow(Base):
    """Frozen guidance content.

    Not guest-linked. This is the product's own content, so guest deletion must
    not touch it - an obvious statement that is exactly the sort of thing a
    cascade gets wrong.
    """

    __tablename__ = "session_definitions"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    practice_id: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    protocol_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    locale: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    version: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    content: Mapped[dict[str, object]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )


class SessionEvent(Base):
    """Append-only playback journal.

    Append-only because a log that can be rewritten is not evidence. The
    repository exposes only append and read, and the unique (session, sequence)
    pair is what makes a retried request idempotent rather than duplicating.

    elapsed_ms is monotonic playback position; occurred_at is wall clock for
    audit. Both are stored because they answer different questions, and
    conflating them is how "this session lasted three hours" bugs happen.
    """

    __tablename__ = "session_events"
    __table_args__ = (
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_events_sequence"),
        sa.CheckConstraint("sequence >= 0", name="ck_session_events_sequence"),
        sa.CheckConstraint("elapsed_ms >= 0", name="ck_session_events_elapsed"),
        sa.CheckConstraint(
            "event_type IN (" + ", ".join(f"'{t}'" for t in SESSION_EVENT_TYPES) + ")",
            name="ck_session_events_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    command_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSONType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )


class SessionResolution(Base):
    """What a device actually resolved a session to — SDD A2.

    Separate from the plan on purpose. The plan is the frozen intent and its
    hash never changes; a resolution records the durations the device measured
    and the output hashes it produced, so it is a different fact with a
    different lifetime.

    Write-once per revision. A rebuilt resolution is a new row with
    ``revision + 1``, never an edit, so the already-played prefix of a session
    stays explainable after a repair. ``server_validated`` records whether the
    backend independently recomputed the hash and agreed - the client reaching
    ``ready`` does not require it, so the two states are stored separately
    rather than collapsed into one boolean.
    """

    __tablename__ = "session_resolutions"
    __table_args__ = (
        sa.UniqueConstraint("session_id", "revision", name="uq_session_resolutions_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_session_resolutions_revision"),
        sa.CheckConstraint("total_ms >= 0", name="ck_session_resolutions_total"),
        sa.CheckConstraint("extended_by_ms >= 0", name="ck_session_resolutions_extended"),
        sa.CheckConstraint("absorbed_ms >= 0", name="ck_session_resolutions_absorbed"),
        sa.CheckConstraint(
            "audio_mode IN ('audible', 'silent_by_choice', 'silent_degraded')",
            name="ck_session_resolutions_mode",
        ),
        sa.CheckConstraint(
            "measurement_source IN ('device_reported', 'plan_estimate')",
            name="ck_session_resolutions_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    resolution_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    plan_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    canonicalization_version: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    timing_policy_version: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    measurement_source: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    audio_mode: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    total_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    extended_by_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    absorbed_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    # The full resolution, so a historical session stays replayable without
    # depending on the planner still producing the same estimates.
    content: Mapped[dict[str, object]] = mapped_column(JSONType, nullable=False)
    server_validated: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )


class AudioRender(Base):
    """A measured render, addressed by its content — SDD section 9.1.

    Keyed by render_key, which derives from the text, locale, voice, style and
    provider version and from nothing about who asked. Two guests who hear the
    same sentence share this row, which is a storage win and a privacy
    property: the table records which content was rendered, never who heard it.

    Nothing is mutated in place. A voice version change produces a different
    key, so old rows age out rather than being overwritten.

    Memory/storage: bounded by the corpus, not by users - roughly 33 utterances
    per voice per locale, so six voices across two locales is about 400 rows
    forever, regardless of how many sessions are played.
    """

    __tablename__ = "audio_renders"
    __table_args__ = (
        sa.CheckConstraint("duration_ms > 0", name="ck_audio_renders_duration"),
        sa.CheckConstraint("byte_size >= 0", name="ck_audio_renders_size"),
    )

    render_key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    locale: Mapped[str] = mapped_column(sa.String(16), nullable=False, index=True)
    voice_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    style: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    provider_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    render_version: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    uri: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )


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
