"""Check-in intake and its normalized engine-facing state vector.

The check-in is the raw user submission. The state vector is the normalized,
frozen representation the deterministic recommendation engine consumes. Keeping
them separate means the wire format can evolve without silently changing the
rule inputs, and it gives every recommendation a stable input fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Goal(StrEnum):
    """User jobs supported by V1. Values are part of the public API contract."""

    STRESS = "stress"
    OVERTHINKING = "overthinking"
    FOCUS = "focus"
    SLEEP = "sleep"
    EMOTIONAL_RESET = "emotional_reset"
    GENERAL = "general"


class ExperienceLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERIENCED = "experienced"


AVAILABLE_MINUTES: tuple[int, ...] = (3, 5, 10, 15, 20)
AvailableMinutes = Literal[3, 5, 10, 15, 20]
Scale = Annotated[int, Field(ge=0, le=10)]

# Rule band thresholds. Defined once so the engine and the reason codes cannot
# drift apart.
VERY_HIGH_STRESS = 8
ELEVATED_STRESS = 6
MODERATE_STRESS = 5
HIGH_MENTAL_ACTIVITY = 7
HIGH_SLEEPINESS = 7


class CheckIn(BaseModel):
    """Raw current-state submission.

    ``extra="forbid"`` keeps the input surface bounded: an unknown field is a
    422 rather than a silently ignored value that changes nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: Goal
    stress: Scale
    energy: Scale
    mental_activity: Scale
    sleepiness: Scale
    available_minutes: AvailableMinutes
    experience_level: ExperienceLevel


class StateVector(BaseModel):
    """Normalized engine input.

    Bounded by construction: one instance per recommendation call, never
    accumulated. The derived band flags are pure functions of the raw scores;
    they exist so a rule and its reason code read from the same predicate.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: Goal
    experience_level: ExperienceLevel
    available_minutes: AvailableMinutes
    stress: Scale
    energy: Scale
    mental_activity: Scale
    sleepiness: Scale

    @classmethod
    def from_check_in(cls, check_in: CheckIn) -> StateVector:
        return cls(
            goal=check_in.goal,
            experience_level=check_in.experience_level,
            available_minutes=check_in.available_minutes,
            stress=check_in.stress,
            energy=check_in.energy,
            mental_activity=check_in.mental_activity,
            sleepiness=check_in.sleepiness,
        )

    @property
    def very_high_stress(self) -> bool:
        return self.stress >= VERY_HIGH_STRESS

    @property
    def elevated_stress(self) -> bool:
        return self.stress >= ELEVATED_STRESS

    @property
    def moderate_stress(self) -> bool:
        return self.stress >= MODERATE_STRESS

    @property
    def high_mental_activity(self) -> bool:
        return self.mental_activity >= HIGH_MENTAL_ACTIVITY

    @property
    def high_sleepiness(self) -> bool:
        return self.sleepiness >= HIGH_SLEEPINESS

    def fingerprint(self) -> str:
        """Stable hash of the normalized input.

        Two check-ins with the same fingerprint must produce the same
        recommendation under the same rules version; the determinism test
        asserts exactly that.
        """
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
