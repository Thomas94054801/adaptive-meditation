"""Practice and protocol knowledge models.

These mirror ``knowledge/practices.v1.yaml`` and ``knowledge/protocols.v1.yaml``.
The knowledge files are the source of truth; the engine never invents a practice
or a protocol stage.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.state.models import ExperienceLevel, Goal, StateVector

Density = Annotated[float, Field(ge=0.0, le=1.0)]

# Named state predicates usable in knowledge files (contraindications and stage
# adaptation). Closed vocabulary: the loader rejects anything else, so a typo in
# YAML fails at startup rather than silently never matching.
StateCondition = Literal[
    "goal_sleep",
    "goal_focus",
    "high_stress",
    "very_high_stress",
    "high_mental_activity",
    "high_sleepiness",
    "high_energy",
    "low_energy",
    "beginner",
    "experienced",
]

EXPERIENCE_ORDER: dict[ExperienceLevel, int] = {
    ExperienceLevel.BEGINNER: 0,
    ExperienceLevel.INTERMEDIATE: 1,
    ExperienceLevel.EXPERIENCED: 2,
}


def condition_holds(condition: StateCondition, state: StateVector) -> bool:
    """Evaluate a named predicate against a state. Total over the vocabulary."""
    match condition:
        case "goal_sleep":
            return state.goal is Goal.SLEEP
        case "goal_focus":
            return state.goal is Goal.FOCUS
        case "high_stress":
            return state.elevated_stress
        case "very_high_stress":
            return state.very_high_stress
        case "high_mental_activity":
            return state.high_mental_activity
        case "high_sleepiness":
            return state.high_sleepiness
        case "high_energy":
            return state.high_energy
        case "low_energy":
            return state.low_energy
        case "beginner":
            return state.experience_level is ExperienceLevel.BEGINNER
        case "experienced":
            return state.experience_level is ExperienceLevel.EXPERIENCED


class Practice(BaseModel):
    """A practice family.

    ``source_basis`` is internal provenance. It is never required in a public
    API response and is stripped by :meth:`public_view`; ``user_facing_source_label``
    is the only field allowed to carry source wording into the UI, and it is
    null for every V1 practice.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    public_name: str
    intent: str
    suitable_for: tuple[Goal, ...]
    source_basis: str
    user_facing_source_label: str | None = None
    default_guidance_density: Density

    # v2 fields. Defaulted so practices.v1.yaml still validates: the V1 replay
    # fixture must keep loading unchanged.
    contraindications: tuple[StateCondition, ...] = ()
    minimum_experience: ExperienceLevel = ExperienceLevel.BEGINNER
    duration_range: tuple[int, int] = (3, 20)
    guidance_density_range: tuple[Density, Density] = (0.0, 1.0)
    outcomes: tuple[str, ...] = ()

    def is_contraindicated_for(self, state: StateVector) -> bool:
        """True when any declared contraindication holds for this state."""
        return any(condition_holds(c, state) for c in self.contraindications)

    def meets_experience_floor(self, level: ExperienceLevel) -> bool:
        return EXPERIENCE_ORDER[level] >= EXPERIENCE_ORDER[self.minimum_experience]

    def public_view(self) -> dict[str, object]:
        return {
            "id": self.id,
            "public_name": self.public_name,
            "intent": self.intent,
            "suitable_for": [goal.value for goal in self.suitable_for],
        }


class ProtocolStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    intent: str
    min_seconds: int = Field(ge=1)
    max_seconds: int = Field(ge=1)
    prompt_template: str = Field(min_length=1, max_length=600)
    silence_after_seconds: int = Field(ge=0)

    # Program005: the wording a returning guest hears instead of
    # prompt_template. Presentation only - the stage's intent, timing and
    # silence are the same whichever text is spoken. The catalog restricts it
    # to a protocol's first stage and to no more words than the canonical text
    # (see validate_returning_template), so a returning opening can only be
    # shorter, never a different practice.
    returning_prompt_template: str | None = Field(default=None, min_length=1, max_length=600)

    # State conditions that lengthen this stage (SDD 2.16). Empty means the
    # stage takes its plain proportional share.
    adaptation: tuple[StateCondition, ...] = ()

    def adaptation_weight(self, state: StateVector | None) -> int:
        """Extra allocation weight for this stage in this state.

        One extra unit per matching condition. Integer, so the allocation stays
        exact and reproducible.
        """
        if state is None:
            return 0
        return sum(1 for condition in self.adaptation if condition_holds(condition, state))

    @model_validator(mode="after")
    def _check_bounds(self) -> ProtocolStage:
        if self.max_seconds < self.min_seconds:
            raise ValueError(f"stage {self.id}: max_seconds < min_seconds")
        if self.silence_after_seconds > self.min_seconds:
            raise ValueError(
                f"stage {self.id}: silence_after_seconds exceeds min_seconds, "
                "the stage could not hold its own silence at the shortest duration"
            )
        return self


class Protocol(BaseModel):
    """An executable protocol for one practice family."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: int = Field(ge=1)
    practice_id: str
    public_title: str
    duration_supported: tuple[int, ...] = Field(min_length=1)
    guidance_density_range: tuple[Density, Density]
    stages: tuple[ProtocolStage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_envelope(self) -> Protocol:
        low, high = self.guidance_density_range
        if high < low:
            raise ValueError(f"protocol {self.id}: guidance_density_range is inverted")
        if len(set(self.duration_supported)) != len(self.duration_supported):
            raise ValueError(f"protocol {self.id}: duplicate duration in duration_supported")
        stage_ids = [stage.id for stage in self.stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError(f"protocol {self.id}: duplicate stage id")
        return self

    @property
    def min_total_seconds(self) -> int:
        return sum(stage.min_seconds for stage in self.stages)

    @property
    def max_total_seconds(self) -> int:
        return sum(stage.max_seconds for stage in self.stages)

    def supports_duration(self, minutes: int) -> bool:
        if minutes not in self.duration_supported:
            return False
        total = minutes * 60
        return self.min_total_seconds <= total <= self.max_total_seconds

    def accepts_density(self, density: float) -> bool:
        low, high = self.guidance_density_range
        return low <= density <= high
