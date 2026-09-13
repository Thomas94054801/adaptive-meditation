"""Wire schemas for the v1 API.

Separate from the domain models so the transport contract can be read in one
place and so ``extra="forbid"`` is applied consistently at the edge.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.recommendation.engine import Recommendation
from app.domain.state.models import CheckIn
from app.persistence.models import NOTES_MAX_LENGTH

Scale = Annotated[int, Field(ge=0, le=10)]


class CheckInResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    created_at: datetime
    check_in: CheckIn


class ExperimentVariantResponse(BaseModel):
    """The variant assigned to this caller for one presentation experiment.

    Returned with the recommendation so the client knows which wording to show.
    Returning it is *assignment*, not exposure: the client reports exposure
    separately, once it has actually rendered the variant.
    """

    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    variant: str


class RecommendationResponse(Recommendation):
    """The engine output, plus the public label the client shows."""

    model_config = ConfigDict(extra="forbid")

    practice_public_name: str
    explanation_variant: ExperimentVariantResponse | None = None


class ExposureRequest(BaseModel):
    """Reports that a variant was actually shown to the user."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(max_length=64)
    context: Annotated[str, Field(min_length=1, max_length=64)]


class ExposureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    variant: str
    context: str
    recorded: bool


class SessionStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    intent: str
    prompt: str
    start_offset_seconds: int
    duration_seconds: int
    guidance_cue_count: int
    silence_after_seconds: int


class SessionPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_id: str
    protocol_version: int
    practice_id: str
    public_title: str
    total_seconds: int
    guidance_density: float
    stages: list[SessionStageResponse]


class SessionCreateRequest(BaseModel):
    """``recommendation`` is optional and, when supplied, is verified.

    The server re-derives the recommendation from the stored check-in. A client
    (or a future AI layer) cannot substitute a different practice family by
    sending one here; a mismatch is a 409, not a silent acceptance.
    """

    model_config = ConfigDict(extra="forbid")

    check_in_id: uuid.UUID
    recommendation: Recommendation | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    check_in_id: uuid.UUID
    status: Literal["created", "started", "completed", "abandoned"]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    recommendation: RecommendationResponse
    plan: SessionPlanResponse
    plan_v2: SessionPlanV2Response | None = None
    run_state: str | None = None


class TimelineSegmentResponse(BaseModel):
    """One segment of the executable timeline.

    ``transcript`` is present on every speech segment, so a client can run the
    whole session as text - which is how a user who cannot use audio completes
    one, not a degraded fallback.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    text: str | None = None
    transcript: str | None = None
    estimated_ms: int | None = None
    render_key: str | None = None
    target_ms: int | None = None
    min_ms: int | None = None
    elastic: bool | None = None
    bell_id: str | None = None
    duration_ms: int | None = None
    asset_key: str | None = None
    marker_id: str | None = None


class SessionPlanV2Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    planner_version: str
    definition_id: str
    plan_hash: str
    practice_id: str
    protocol_id: str
    public_title: str
    locale: str
    target_total_ms: int
    minimum_total_ms: int
    shrinkable_ms: int
    guidance_density: float
    segments: list[TimelineSegmentResponse]


class PlaybackCommandRequest(BaseModel):
    """A state-changing playback command.

    ``command_id`` makes a retry idempotent and ``sequence`` makes an
    out-of-order arrival droppable, which is what rapid play/pause taps on a
    flaky connection actually look like.
    """

    model_config = ConfigDict(extra="forbid")

    command: Literal[
        "prepare",
        "resolved",
        "unresolvable",
        "start",
        "pause",
        "resume",
        "interrupt",
        "interruption_ended",
        "complete",
        "abandon",
        "fail",
        "recover",
    ]
    command_id: str = Field(min_length=1, max_length=64)
    sequence: Annotated[int, Field(ge=0)]
    """One counter per session, shared with the event journal, strictly increasing."""
    elapsed_ms: Annotated[int, Field(ge=0)] = 0
    segment_id: Annotated[str, Field(max_length=64)] | None = None


class PlaybackStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    run_state: str
    elapsed_ms: int
    last_segment_id: str | None
    command_sequence: int
    applied: bool
    """False when the command was a replay or arrived out of order."""
    resume_segment_id: str | None = None
    """Where a client resumes after process death. Never mid-utterance."""
    resume_offset_ms: int = 0


class RenderManifestEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    render_key: str
    duration_ms: int
    content_sha256: str
    """Verified before playing. A mismatch is deleted and re-fetched, not played."""
    uri: str


class RenderManifestResponse(BaseModel):
    """What a client needs to warm its cache before a session is ready."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    plan_hash: str
    provider_id: str
    locale: str
    entries: list[RenderManifestEntryResponse]
    unresolved: list[str]
    """Segment ids the backend could not resolve. The client renders these with
    device-native TTS, or shows the transcript. Not an error: with device TTS as
    the shipped provider, every segment being unresolved is the normal case."""
    complete: bool


SessionEventType = Literal[
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
]


class SessionEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: Annotated[int, Field(ge=0)]
    event_type: SessionEventType
    """Closed set. An unrecognised type is a client bug, not a row to store."""
    segment_id: Annotated[str, Field(max_length=64)] | None = None
    elapsed_ms: Annotated[int, Field(ge=0)] = 0
    command_id: Annotated[str, Field(max_length=64)] | None = None
    detail: dict[str, Any] | None = None


class SessionEventBatchRequest(BaseModel):
    """Events batch so a session does not make a round trip per segment."""

    model_config = ConfigDict(extra="forbid")

    events: Annotated[list[SessionEventRequest], Field(min_length=1, max_length=200)]


class SessionEventBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: int
    duplicates: int
    """Replayed sequences, recorded once. A retry is safe, not an error."""


class SessionFeedbackRequest(BaseModel):
    """Outcome feedback. No clinical meaning is inferred from these values.

    v2 accepts the full after-state so every goal-specific outcome measure can
    be computed. All four are optional: a client that sends only ``after_score``
    still works, and its session simply has no derived outcome.
    """

    model_config = ConfigDict(extra="forbid")

    after_score: Scale
    helpfulness: Annotated[int, Field(ge=1, le=5)]
    completed: bool
    before_score: Scale | None = None
    notes: Annotated[str, Field(max_length=NOTES_MAX_LENGTH)] | None = None

    stress_after: Scale | None = None
    energy_after: Scale | None = None
    mental_activity_after: Scale | None = None
    sleepiness_after: Scale | None = None
    completion_ratio: Annotated[float, Field(ge=0.0, le=1.0)] | None = None


class CandidateResponse(BaseModel):
    """One scored candidate. Debug and offline evaluation only.

    ``score`` is a bounded ordinal ranking aid, not a probability.
    """

    model_config = ConfigDict(extra="forbid")

    practice_id: str
    score: Annotated[int, Field(ge=0, le=100)]
    reason_codes: list[str]


class CandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set_version: str
    candidates: list[CandidateResponse]
    exclusions: list[dict[str, str]]


class SessionSummary(BaseModel):
    """One row of a guest's history."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: str
    created_at: datetime
    completed_at: datetime | None
    practice_id: str
    public_title: str
    duration_minutes: int
    rule_set_version: str | None
    # product optimization metric only - never rendered to the user
    outcome_score: int | None


class SessionHistoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SessionSummary]
    next_cursor: str | None
    has_more: bool


class GuestExportResponse(BaseModel):
    """Everything stored for one guest."""

    model_config = ConfigDict(extra="forbid")

    guest_id: uuid.UUID
    check_ins: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
    feedback: list[dict[str, Any]]
    experiment_assignments: list[dict[str, Any]]
    experiment_exposures: list[dict[str, Any]]
    playback_events: list[dict[str, Any]]
    """The playback journal. A new table the export omits is a privacy defect."""


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    app_env: str
    api_version: str
    engine_version: str
    rule_set_version: str
    knowledge_version: int
    practices_loaded: int
    protocols_loaded: int
    ai_provider_configured: bool


class DisclaimerResponse(BaseModel):
    """The single wellness disclaimer surface."""

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
