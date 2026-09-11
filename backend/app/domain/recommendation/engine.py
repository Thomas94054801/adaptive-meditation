"""Deterministic State -> Practice engine.

Pure domain logic: no database, no HTTP, no generative provider. The only
collaborator is the immutable knowledge catalog, which is read-only.

Determinism contract: for one ``RULES_VERSION`` and one knowledge catalog, equal
normalized input produces an equal ``Recommendation``, field for field, including
reason-code order.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.practice.catalog import KnowledgeCatalog, KnowledgeValidationError
from app.domain.recommendation.rules import (
    ALLOWED_REASON_CODES,
    RULES_VERSION,
    PracticeId,
    PracticeSelection,
    ReasonCode,
    select_duration,
    select_guidance_density,
    select_practice,
)
from app.domain.state.models import CheckIn, StateVector


class RecommendationError(RuntimeError):
    """Raised when the rules and the knowledge catalog disagree."""


class Recommendation(BaseModel):
    """The deterministic engine output. This is the envelope AI may not change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    practice_id: str
    duration_minutes: int = Field(ge=1)
    guidance_density: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...]
    recommendation_version: str = RULES_VERSION


class RecommendationEngine:
    """Stateless facade over the rules. Safe to share across requests."""

    def __init__(self, catalog: KnowledgeCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> KnowledgeCatalog:
        return self._catalog

    def recommend(self, check_in: CheckIn) -> Recommendation:
        return self.recommend_for_state(StateVector.from_check_in(check_in))

    def recommend_for_state(self, state: StateVector) -> Recommendation:
        selection = select_practice(state)
        practice_id, codes = self._resolve_practice(selection)

        allowed = ALLOWED_REASON_CODES[state.goal]
        unexpected = [code.value for code in codes if code not in allowed]
        if unexpected:  # pragma: no cover - guarded by the vocabulary test
            raise RecommendationError(
                f"rule for goal {state.goal.value!r} emitted reason codes outside its "
                f"vocabulary: {unexpected}"
            )

        protocol = self._catalog.protocol_for(practice_id.value)
        duration_minutes = select_duration(state, protocol.duration_supported)
        guidance_density = select_guidance_density(state, practice_id)

        if not protocol.accepts_density(guidance_density):
            raise RecommendationError(
                f"guidance density {guidance_density} falls outside the declared range "
                f"{protocol.guidance_density_range} of protocol {protocol.id!r}"
            )
        if not protocol.supports_duration(duration_minutes):
            raise RecommendationError(
                f"protocol {protocol.id!r} cannot render {duration_minutes} minutes"
            )

        return Recommendation(
            practice_id=practice_id.value,
            duration_minutes=duration_minutes,
            guidance_density=guidance_density,
            reason_codes=tuple(code.value for code in codes),
            recommendation_version=RULES_VERSION,
        )

    def _resolve_practice(
        self, selection: PracticeSelection
    ) -> tuple[PracticeId, tuple[ReasonCode, ...]]:
        """Pick the primary practice, or the declared fallback if it is unreachable.

        A rule may name a fallback for the case where the primary family has no
        executable protocol in the catalog. Falling back is recorded in the
        reason codes; it is never silent.
        """
        if self._catalog.has_executable_protocol(selection.primary.value):
            return selection.primary, selection.reason_codes
        if selection.fallback is not None and self._catalog.has_executable_protocol(
            selection.fallback.value
        ):
            return selection.fallback, (*selection.reason_codes, ReasonCode.FALLBACK_PRACTICE_USED)
        raise KnowledgeValidationError(
            f"selected practice {selection.primary.value!r} has no executable protocol "
            "and no usable fallback"
        )
