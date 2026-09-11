"""Outcome evidence.

Raw before and after values are the record. Everything in this module is a
*derived* view of them and is recomputable; nothing here ever overwrites the
raw values, because a derived number that replaced its inputs cannot be
recomputed when the derivation changes.

``session_outcome_score`` is a **product optimization metric only**. It is not a
clinical score, not a medical score and not a diagnostic score, it carries no
validation of any kind, and it is never shown to a user.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.domain.state.models import Goal

SCORE_MIN = 0
SCORE_MAX = 100


class OutcomeMeasure(StrEnum):
    """What "better" means for a given goal."""

    STRESS_REDUCTION = "stress_reduction"
    MENTAL_QUIETING = "mental_quieting"
    SLEEP_ONSET = "sleep_onset"
    ACTIVATION = "activation"
    GENERAL_HELPFULNESS = "general_helpfulness"


# Primary and optional secondary measure per goal (SDD_PROGRAM002 section 2.8).
GOAL_MEASURES: dict[Goal, tuple[OutcomeMeasure, OutcomeMeasure | None]] = {
    Goal.STRESS: (OutcomeMeasure.STRESS_REDUCTION, None),
    Goal.OVERTHINKING: (OutcomeMeasure.MENTAL_QUIETING, None),
    Goal.SLEEP: (OutcomeMeasure.SLEEP_ONSET, None),
    Goal.FOCUS: (OutcomeMeasure.ACTIVATION, OutcomeMeasure.MENTAL_QUIETING),
    Goal.EMOTIONAL_RESET: (OutcomeMeasure.STRESS_REDUCTION, None),
    Goal.GENERAL: (OutcomeMeasure.GENERAL_HELPFULNESS, None),
}


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """The four self-reported scales, before or after a session."""

    stress: int
    energy: int
    mental_activity: int
    sleepiness: int

    def as_dict(self) -> dict[str, int]:
        return {
            "stress": self.stress,
            "energy": self.energy,
            "mental_activity": self.mental_activity,
            "sleepiness": self.sleepiness,
        }


def measure_delta(
    measure: OutcomeMeasure, before: StateSnapshot, after: StateSnapshot, helpfulness: int
) -> int:
    """Signed movement for one measure. Positive is always the intended direction."""
    match measure:
        case OutcomeMeasure.STRESS_REDUCTION:
            return before.stress - after.stress
        case OutcomeMeasure.MENTAL_QUIETING:
            return before.mental_activity - after.mental_activity
        case OutcomeMeasure.SLEEP_ONSET:
            return after.sleepiness - before.sleepiness
        case OutcomeMeasure.ACTIVATION:
            return after.energy - before.energy
        case OutcomeMeasure.GENERAL_HELPFULNESS:
            return helpfulness


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """Derived outcome evidence for one session."""

    goal: Goal
    before: StateSnapshot
    after: StateSnapshot
    helpfulness: int
    completion_ratio: float
    primary_measure: OutcomeMeasure
    primary_delta: int
    secondary_measure: OutcomeMeasure | None
    secondary_delta: int | None
    outcome_score: int

    def as_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal.value,
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
            "helpfulness": self.helpfulness,
            "completion_ratio": self.completion_ratio,
            "primary_measure": self.primary_measure.value,
            "primary_delta": self.primary_delta,
            "secondary_measure": (self.secondary_measure.value if self.secondary_measure else None),
            "secondary_delta": self.secondary_delta,
            # product optimization metric only - not clinical, not diagnostic
            "outcome_score": self.outcome_score,
        }


def compute_outcome(
    *,
    goal: Goal,
    before: StateSnapshot,
    after: StateSnapshot,
    helpfulness: int,
    completion_ratio: float,
) -> SessionOutcome:
    """Derive the outcome view of one session's raw before/after values."""
    primary, secondary = GOAL_MEASURES[goal]
    primary_delta = measure_delta(primary, before, after, helpfulness)
    secondary_delta = measure_delta(secondary, before, after, helpfulness) if secondary else None
    return SessionOutcome(
        goal=goal,
        before=before,
        after=after,
        helpfulness=helpfulness,
        completion_ratio=completion_ratio,
        primary_measure=primary,
        primary_delta=primary_delta,
        secondary_measure=secondary,
        secondary_delta=secondary_delta,
        outcome_score=session_outcome_score(
            primary_measure=primary,
            primary_delta=primary_delta,
            helpfulness=helpfulness,
            completion_ratio=completion_ratio,
        ),
    )


def session_outcome_score(
    *,
    primary_measure: OutcomeMeasure,
    primary_delta: int,
    helpfulness: int,
    completion_ratio: float,
) -> int:
    """Bounded 0..100 product optimization metric. **Not a clinical score.**

    Three weighted parts: how far the primary measure moved (50), how useful the
    user said it was (30), and how much of the session they actually did (20).
    The weights are a product judgement, not an estimate of anything, and the
    result has no calibration and no units.
    """
    if primary_measure is OutcomeMeasure.GENERAL_HELPFULNESS:
        # helpfulness is 1..5, not a -10..10 delta.
        movement = Decimal(max(0, min(4, primary_delta - 1))) / Decimal(4)
    else:
        clamped = max(-10, min(10, primary_delta))
        movement = (Decimal(clamped) + Decimal(10)) / Decimal(20)

    usefulness = Decimal(max(0, min(4, helpfulness - 1))) / Decimal(4)
    completion = Decimal(str(max(0.0, min(1.0, completion_ratio))))

    total = movement * 50 + usefulness * 30 + completion * 20
    return max(SCORE_MIN, min(SCORE_MAX, _round_half_up(total)))
