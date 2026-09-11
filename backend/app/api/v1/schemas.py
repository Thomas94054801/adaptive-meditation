"""Wire schemas for the v1 API.

Separate from the domain models so the transport contract can be read in one
place and so ``extra="forbid"`` is applied consistently at the edge.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

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


class RecommendationResponse(Recommendation):
    """The engine output, plus the public label the client shows."""

    model_config = ConfigDict(extra="forbid")

    practice_public_name: str


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


class SessionFeedbackRequest(BaseModel):
    """Outcome feedback. No clinical meaning is inferred from these values."""

    model_config = ConfigDict(extra="forbid")

    after_score: Scale
    helpfulness: Annotated[int, Field(ge=1, le=5)]
    completed: bool
    before_score: Scale | None = None
    notes: Annotated[str, Field(max_length=NOTES_MAX_LENGTH)] | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    app_env: str
    api_version: str
    rules_version: str
    practices_loaded: int
    protocols_loaded: int
    ai_provider_configured: bool


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
