"""Rule vocabulary, policy tables and the priority-ordered selection rules.

Everything in this module is pure data or pure functions of a
:class:`~app.domain.state.models.StateVector`. No I/O, no database, no provider.
The rules version is part of the recommendation output: changing any table here
without bumping ``RULES_VERSION`` would silently break the determinism contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.domain.state.models import ExperienceLevel, Goal, StateVector

RULES_VERSION = "1"


class PracticeId(StrEnum):
    """Practice families the rules may select. Must exist in the knowledge catalog."""

    BREATH_AWARENESS = "breath_awareness"
    BODY_AWARENESS = "body_awareness"
    FEELING_TONE = "feeling_tone"
    THOUGHT_OBSERVATION = "thought_observation"
    KINDNESS = "kindness"
    OPEN_AWARENESS = "open_awareness"


class ReasonCode(StrEnum):
    """Why a recommendation was selected. Emitted in a fixed order per rule."""

    GOAL_SLEEP = "goal_sleep"
    GOAL_OVERTHINKING = "goal_overthinking"
    GOAL_STRESS = "goal_stress"
    GOAL_FOCUS = "goal_focus"
    GOAL_EMOTIONAL_RESET = "goal_emotional_reset"
    GOAL_GENERAL = "goal_general"

    HIGH_MENTAL_ACTIVITY = "high_mental_activity"
    HIGH_STRESS = "high_stress"
    VERY_HIGH_STRESS = "very_high_stress"
    MODERATE_STRESS = "moderate_stress"
    HIGH_SLEEPINESS = "high_sleepiness"

    GROUNDING_PREFERRED = "grounding_preferred"
    COGNITIVE_OBSERVATION = "cognitive_observation"
    STABILIZE_ATTENTION = "stabilize_attention"
    EXPERIENCED_OPEN_AWARENESS = "experienced_open_awareness"
    RECOGNIZE_REACTIVITY = "recognize_reactivity"
    EXPERIENCE_PROGRESSION = "experience_progression"
    FALLBACK_PRACTICE_USED = "fallback_practice_used"


# The reason codes each goal is allowed to emit. A rule that emits anything
# outside its own vocabulary is a defect, and the test suite asserts it.
ALLOWED_REASON_CODES: dict[Goal, frozenset[ReasonCode]] = {
    Goal.SLEEP: frozenset(
        {
            ReasonCode.GOAL_SLEEP,
            ReasonCode.HIGH_MENTAL_ACTIVITY,
            ReasonCode.GROUNDING_PREFERRED,
            ReasonCode.FALLBACK_PRACTICE_USED,
        }
    ),
    Goal.OVERTHINKING: frozenset(
        {
            ReasonCode.GOAL_OVERTHINKING,
            ReasonCode.HIGH_MENTAL_ACTIVITY,
            ReasonCode.HIGH_STRESS,
            ReasonCode.COGNITIVE_OBSERVATION,
        }
    ),
    Goal.STRESS: frozenset(
        {
            ReasonCode.GOAL_STRESS,
            ReasonCode.VERY_HIGH_STRESS,
            ReasonCode.MODERATE_STRESS,
            ReasonCode.EXPERIENCED_OPEN_AWARENESS,
        }
    ),
    Goal.FOCUS: frozenset(
        {
            ReasonCode.GOAL_FOCUS,
            ReasonCode.HIGH_SLEEPINESS,
            ReasonCode.STABILIZE_ATTENTION,
        }
    ),
    Goal.EMOTIONAL_RESET: frozenset(
        {
            ReasonCode.GOAL_EMOTIONAL_RESET,
            ReasonCode.RECOGNIZE_REACTIVITY,
        }
    ),
    Goal.GENERAL: frozenset(
        {
            ReasonCode.GOAL_GENERAL,
            ReasonCode.EXPERIENCE_PROGRESSION,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class PracticeSelection:
    """Outcome of the practice-selection rules, before catalog resolution."""

    primary: PracticeId
    reason_codes: tuple[ReasonCode, ...]
    fallback: PracticeId | None = None


def select_practice(state: StateVector) -> PracticeSelection:
    """Priority-ordered practice selection. Total over the Goal enum."""
    match state.goal:
        case Goal.SLEEP:
            return _sleep(state)
        case Goal.OVERTHINKING:
            return _overthinking(state)
        case Goal.STRESS:
            return _stress(state)
        case Goal.FOCUS:
            return _focus(state)
        case Goal.EMOTIONAL_RESET:
            return _emotional_reset(state)
        case Goal.GENERAL:
            return _general(state)


def _sleep(state: StateVector) -> PracticeSelection:
    codes = [ReasonCode.GOAL_SLEEP]
    if state.high_mental_activity:
        codes.append(ReasonCode.HIGH_MENTAL_ACTIVITY)
    codes.append(ReasonCode.GROUNDING_PREFERRED)
    # High mental activity keeps a declared fallback; settling is still led by
    # the body, but breath work is the stated alternative if grounding is not
    # available in the catalog.
    fallback = PracticeId.BREATH_AWARENESS if state.high_mental_activity else None
    return PracticeSelection(PracticeId.BODY_AWARENESS, tuple(codes), fallback)


def _overthinking(state: StateVector) -> PracticeSelection:
    codes = [ReasonCode.GOAL_OVERTHINKING]
    if state.high_mental_activity and state.elevated_stress:
        codes += [ReasonCode.HIGH_MENTAL_ACTIVITY, ReasonCode.HIGH_STRESS]
        return PracticeSelection(PracticeId.BODY_AWARENESS, tuple(codes))
    if state.high_mental_activity:
        codes += [ReasonCode.HIGH_MENTAL_ACTIVITY, ReasonCode.COGNITIVE_OBSERVATION]
        return PracticeSelection(PracticeId.THOUGHT_OBSERVATION, tuple(codes))
    return PracticeSelection(PracticeId.BREATH_AWARENESS, tuple(codes))


def _stress(state: StateVector) -> PracticeSelection:
    codes = [ReasonCode.GOAL_STRESS]
    if state.very_high_stress:
        codes.append(ReasonCode.VERY_HIGH_STRESS)
        return PracticeSelection(PracticeId.BODY_AWARENESS, tuple(codes))
    if state.moderate_stress:
        codes.append(ReasonCode.MODERATE_STRESS)
        return PracticeSelection(PracticeId.BREATH_AWARENESS, tuple(codes))
    if state.experience_level is ExperienceLevel.EXPERIENCED:
        codes.append(ReasonCode.EXPERIENCED_OPEN_AWARENESS)
        return PracticeSelection(PracticeId.OPEN_AWARENESS, tuple(codes))
    return PracticeSelection(PracticeId.BREATH_AWARENESS, tuple(codes))


def _focus(state: StateVector) -> PracticeSelection:
    codes = [ReasonCode.GOAL_FOCUS]
    if state.high_sleepiness:
        codes.append(ReasonCode.HIGH_SLEEPINESS)
        return PracticeSelection(PracticeId.BODY_AWARENESS, tuple(codes))
    codes.append(ReasonCode.STABILIZE_ATTENTION)
    return PracticeSelection(PracticeId.BREATH_AWARENESS, tuple(codes))


def _emotional_reset(state: StateVector) -> PracticeSelection:
    codes = [ReasonCode.GOAL_EMOTIONAL_RESET]
    if state.experience_level is ExperienceLevel.BEGINNER:
        return PracticeSelection(PracticeId.BODY_AWARENESS, tuple(codes))
    codes.append(ReasonCode.RECOGNIZE_REACTIVITY)
    return PracticeSelection(PracticeId.FEELING_TONE, tuple(codes))


def _general(state: StateVector) -> PracticeSelection:
    codes = [ReasonCode.GOAL_GENERAL]
    if state.experience_level is ExperienceLevel.BEGINNER:
        return PracticeSelection(PracticeId.BREATH_AWARENESS, tuple(codes))
    codes.append(ReasonCode.EXPERIENCE_PROGRESSION)
    if state.experience_level is ExperienceLevel.INTERMEDIATE:
        return PracticeSelection(PracticeId.BODY_AWARENESS, tuple(codes))
    return PracticeSelection(PracticeId.OPEN_AWARENESS, tuple(codes))


# --- duration policy (SDD 5.2) ------------------------------------------------

DURATION_POLICY: dict[int, dict[ExperienceLevel, int]] = {
    3: {
        ExperienceLevel.BEGINNER: 3,
        ExperienceLevel.INTERMEDIATE: 3,
        ExperienceLevel.EXPERIENCED: 3,
    },
    5: {
        ExperienceLevel.BEGINNER: 5,
        ExperienceLevel.INTERMEDIATE: 5,
        ExperienceLevel.EXPERIENCED: 5,
    },
    10: {
        ExperienceLevel.BEGINNER: 10,
        ExperienceLevel.INTERMEDIATE: 10,
        ExperienceLevel.EXPERIENCED: 10,
    },
    15: {
        ExperienceLevel.BEGINNER: 10,
        ExperienceLevel.INTERMEDIATE: 15,
        ExperienceLevel.EXPERIENCED: 15,
    },
    20: {
        ExperienceLevel.BEGINNER: 10,
        ExperienceLevel.INTERMEDIATE: 15,
        ExperienceLevel.EXPERIENCED: 20,
    },
}


def select_duration(state: StateVector, supported: tuple[int, ...]) -> int:
    """Policy duration, clamped to what the chosen protocol can actually render.

    Never exceeds ``available_minutes``: the clamp only ever steps down.
    """
    target = DURATION_POLICY[state.available_minutes][state.experience_level]
    if target > state.available_minutes:  # pragma: no cover - table invariant
        raise ValueError("duration policy produced a value above available_minutes")
    if target in supported:
        return target
    candidates = [minutes for minutes in supported if minutes <= target]
    if not candidates:
        raise ValueError(f"protocol supports {supported} but the policy asked for {target} minutes")
    return max(candidates)


# --- guidance density policy (SDD 5.3) ---------------------------------------

BASE_DENSITY: dict[ExperienceLevel, Decimal] = {
    ExperienceLevel.BEGINNER: Decimal("0.65"),
    ExperienceLevel.INTERMEDIATE: Decimal("0.50"),
    ExperienceLevel.EXPERIENCED: Decimal("0.35"),
}
HIGH_STRESS_BONUS = Decimal("0.05")
DENSITY_CEILING = Decimal("0.75")
SLEEP_DENSITY_CEILING = Decimal("0.65")
OPEN_AWARENESS_ADJUSTMENT = Decimal("-0.10")
OPEN_AWARENESS_FLOOR = Decimal("0.20")


def select_guidance_density(state: StateVector, practice_id: PracticeId) -> float:
    """Apply the density adjustments in declared order and round half-up to 2dp.

    Decimal rather than float: 0.65 + 0.05 must be 0.70, not 0.7000000000000001,
    because the value is persisted, compared for equality and sent to a client.
    """
    density = BASE_DENSITY[state.experience_level]
    if state.very_high_stress:
        density = min(density + HIGH_STRESS_BONUS, DENSITY_CEILING)
    if state.goal is Goal.SLEEP:
        density = min(density, SLEEP_DENSITY_CEILING)
    if practice_id is PracticeId.OPEN_AWARENESS:
        density = max(density + OPEN_AWARENESS_ADJUSTMENT, OPEN_AWARENESS_FLOOR)
    return float(density.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
