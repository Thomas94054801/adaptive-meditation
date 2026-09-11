"""Deterministic State -> Practice engine.

Pure domain logic: no database, no HTTP, no generative provider. The only
collaborator is the immutable knowledge catalog, which is read-only.

Determinism contract: for one ``RULES_VERSION`` and one knowledge catalog, equal
normalized input produces an equal ``Recommendation``, field for field, including
reason-code order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.rules import (
    ALLOWED_REASON_CODES,
    select_duration,
    select_guidance_density,
)
from app.domain.recommendation.rules_v2 import ALLOWED_REASON_CODES_V2
from app.domain.recommendation.rulesets import RuleSet, V2RuleSet
from app.domain.recommendation.scoring import RuleOutcome
from app.domain.recommendation.versions import (
    DEFAULT_PROTOCOL_VERSION,
    ENGINE_VERSION,
    LEGACY_ENGINE_VERSION,
    RuleSetVersion,
)
from app.domain.state.models import CheckIn, StateVector


class RecommendationError(RuntimeError):
    """Raised when the rules and the knowledge catalog disagree."""


class Recommendation(BaseModel):
    """The deterministic engine output. This is the envelope AI may not change.

    v2 splits Program001's single ``recommendation_version`` into three fields
    that move independently, and records the input fingerprint so a stored
    recommendation can be replayed without the original check-in.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    practice_id: str
    duration_minutes: int = Field(ge=1)
    guidance_density: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...]

    engine_version: str = ENGINE_VERSION
    rule_set_version: str = RuleSetVersion.V2.value
    protocol_version: str = DEFAULT_PROTOCOL_VERSION
    state_fingerprint: str = ""

    @classmethod
    def from_stored(cls, payload: Mapping[str, Any]) -> Recommendation:
        """Read a persisted recommendation from any engine version.

        A Program001 row carries only ``recommendation_version``. Rather than
        migrating those rows - which would destroy the record of what was
        actually served - the legacy field is interpreted here, once, at the
        edge.
        """
        data = dict(payload)
        legacy = data.pop("recommendation_version", None)
        if "engine_version" not in data:
            data["engine_version"] = LEGACY_ENGINE_VERSION
            data["rule_set_version"] = str(legacy or RuleSetVersion.V1.value)
            data.setdefault("protocol_version", LEGACY_ENGINE_VERSION)
        data.setdefault("state_fingerprint", "")
        return cls.model_validate(data)


class RecommendationEngine:
    """Stateless facade over a rule set. Safe to share across requests."""

    def __init__(self, catalog: KnowledgeCatalog, rule_set: RuleSet | None = None) -> None:
        self._catalog = catalog
        self._rule_set: RuleSet = rule_set or V2RuleSet()

    @property
    def catalog(self) -> KnowledgeCatalog:
        return self._catalog

    @property
    def rule_set(self) -> RuleSet:
        return self._rule_set

    def recommend(self, check_in: CheckIn) -> Recommendation:
        return self.recommend_for_state(StateVector.from_check_in(check_in))

    def evaluate(self, state: StateVector) -> RuleOutcome:
        """Full candidate list. For the offline evaluator and the debug path."""
        return self._rule_set.evaluate(state, self._catalog)

    def recommend_for_state(self, state: StateVector) -> Recommendation:
        outcome = self.evaluate(state)
        winner = outcome.winner
        practice_id = winner.practice_id
        codes = winner.reason_codes

        allowed = (
            ALLOWED_REASON_CODES_V2[state.goal]
            if outcome.rule_set_version == RuleSetVersion.V2.value
            else ALLOWED_REASON_CODES[state.goal]
        )
        unexpected = [code.value for code in codes if code not in allowed]
        if unexpected:  # pragma: no cover - guarded by the vocabulary test
            raise RecommendationError(
                f"rule set {outcome.rule_set_version} emitted reason codes outside the "
                f"vocabulary for goal {state.goal.value!r}: {unexpected}"
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
            engine_version=ENGINE_VERSION,
            rule_set_version=outcome.rule_set_version,
            protocol_version=str(self._catalog.protocols_schema_version),
            state_fingerprint=state.fingerprint(),
        )
