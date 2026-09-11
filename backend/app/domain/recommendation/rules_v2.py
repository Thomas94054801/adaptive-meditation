"""Rule set v2: eligibility filters, base affinity and scored modifiers.

Pure data and pure functions of a StateVector. Selection is a scored ranking,
not a first-match cascade, so a near-miss is visible to the offline evaluator
instead of being invisible behind the rule that happened to fire first.

Determinism: candidate order is ``(-score, declaration_index)`` where the index
is the practice's fixed position in ``PracticeId``. Nothing here iterates a set
or depends on dict insertion order for its result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.rules import PracticeId, ReasonCode
from app.domain.recommendation.scoring import Candidate, Exclusion, RuleOutcome, clamp_score
from app.domain.recommendation.versions import RuleSetVersion
from app.domain.state.models import ExperienceLevel, Goal, StateVector

GOAL_REASON_CODE: dict[Goal, ReasonCode] = {
    Goal.STRESS: ReasonCode.GOAL_STRESS,
    Goal.OVERTHINKING: ReasonCode.GOAL_OVERTHINKING,
    Goal.FOCUS: ReasonCode.GOAL_FOCUS,
    Goal.SLEEP: ReasonCode.GOAL_SLEEP,
    Goal.EMOTIONAL_RESET: ReasonCode.GOAL_EMOTIONAL_RESET,
    Goal.GENERAL: ReasonCode.GOAL_GENERAL,
}

# Declaration order fixes every tie-break in the rule set.
PRACTICE_ORDER: tuple[PracticeId, ...] = (
    PracticeId.BREATH_AWARENESS,
    PracticeId.BODY_AWARENESS,
    PracticeId.FEELING_TONE,
    PracticeId.THOUGHT_OBSERVATION,
    PracticeId.KINDNESS,
    PracticeId.OPEN_AWARENESS,
    PracticeId.MINDFUL_WALKING,
)
PRACTICE_INDEX: dict[PracticeId, int] = {p: i for i, p in enumerate(PRACTICE_ORDER)}

# --- base affinity -----------------------------------------------------------
# How well each practice fits each goal before the state is considered.
BASE_AFFINITY: dict[Goal, dict[PracticeId, int]] = {
    Goal.STRESS: {
        PracticeId.BREATH_AWARENESS: 62,
        PracticeId.BODY_AWARENESS: 60,
        PracticeId.FEELING_TONE: 50,
        PracticeId.KINDNESS: 45,
        PracticeId.OPEN_AWARENESS: 40,
        PracticeId.THOUGHT_OBSERVATION: 35,
        PracticeId.MINDFUL_WALKING: 35,
    },
    Goal.OVERTHINKING: {
        PracticeId.THOUGHT_OBSERVATION: 60,
        PracticeId.BREATH_AWARENESS: 58,
        PracticeId.BODY_AWARENESS: 55,
        PracticeId.FEELING_TONE: 45,
        PracticeId.MINDFUL_WALKING: 40,
        PracticeId.OPEN_AWARENESS: 35,
        PracticeId.KINDNESS: 35,
    },
    Goal.FOCUS: {
        PracticeId.BREATH_AWARENESS: 62,
        PracticeId.BODY_AWARENESS: 50,
        PracticeId.MINDFUL_WALKING: 45,
        PracticeId.OPEN_AWARENESS: 40,
        PracticeId.THOUGHT_OBSERVATION: 40,
        PracticeId.FEELING_TONE: 30,
        PracticeId.KINDNESS: 25,
    },
    Goal.SLEEP: {
        PracticeId.BODY_AWARENESS: 70,
        PracticeId.BREATH_AWARENESS: 55,
        PracticeId.KINDNESS: 45,
        PracticeId.FEELING_TONE: 40,
        PracticeId.OPEN_AWARENESS: 30,
        PracticeId.THOUGHT_OBSERVATION: 30,
        PracticeId.MINDFUL_WALKING: 0,
    },
    Goal.EMOTIONAL_RESET: {
        PracticeId.FEELING_TONE: 58,
        PracticeId.KINDNESS: 56,
        PracticeId.BODY_AWARENESS: 55,
        PracticeId.BREATH_AWARENESS: 45,
        PracticeId.OPEN_AWARENESS: 40,
        PracticeId.THOUGHT_OBSERVATION: 35,
        PracticeId.MINDFUL_WALKING: 30,
    },
    Goal.GENERAL: {
        PracticeId.BREATH_AWARENESS: 55,
        PracticeId.BODY_AWARENESS: 52,
        PracticeId.OPEN_AWARENESS: 45,
        PracticeId.FEELING_TONE: 42,
        PracticeId.THOUGHT_OBSERVATION: 40,
        PracticeId.KINDNESS: 40,
        PracticeId.MINDFUL_WALKING: 35,
    },
}


# --- modifiers ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Modifier:
    """One scored adjustment.

    ``reason_codes`` is empty for a de-emphasis: reason codes explain why the
    winner won, and a penalty applied to a practice that loses anyway needs no
    user-visible justification.
    """

    name: str
    practice: PracticeId
    delta: int
    predicate: Callable[[StateVector], bool]
    reason_codes: tuple[ReasonCode, ...] = field(default=())


def _moderate_stress(state: StateVector) -> bool:
    """5..7: stressed, but not at the band where grounding dominates."""
    return state.moderate_stress and not state.very_high_stress


def _kindness_window(state: StateVector) -> bool:
    """Emotional reset, carrying real stress, without a racing mind.

    This is the rule that makes kindness reachable (SDD_PROGRAM002 2.3). It is
    narrow on purpose: with a racing mind, grounding comes first, and without
    stress, feeling-tone work is the better fit.
    """
    return (
        state.goal is Goal.EMOTIONAL_RESET
        and state.elevated_stress
        and not state.high_mental_activity
    )


def _walking_window(state: StateVector) -> bool:
    """Focus with high energy: use the body's state instead of fighting it."""
    return state.goal is Goal.FOCUS and state.high_energy


MODIFIERS: tuple[Modifier, ...] = (
    # Very high stress: ground first, and de-emphasise anything cognitive or open.
    Modifier(
        "very_high_stress_body",
        PracticeId.BODY_AWARENESS,
        20,
        lambda s: s.very_high_stress,
        (ReasonCode.VERY_HIGH_STRESS,),
    ),
    Modifier(
        "very_high_stress_breath", PracticeId.BREATH_AWARENESS, 5, lambda s: s.very_high_stress
    ),
    Modifier(
        "very_high_stress_thought",
        PracticeId.THOUGHT_OBSERVATION,
        -15,
        lambda s: s.very_high_stress,
    ),
    Modifier("very_high_stress_open", PracticeId.OPEN_AWARENESS, -15, lambda s: s.very_high_stress),
    Modifier(
        "very_high_stress_walking", PracticeId.MINDFUL_WALKING, -10, lambda s: s.very_high_stress
    ),
    # Moderate stress: the breath is the steadiest single anchor.
    Modifier(
        "moderate_stress_breath",
        PracticeId.BREATH_AWARENESS,
        6,
        _moderate_stress,
        (ReasonCode.MODERATE_STRESS,),
    ),
    Modifier("moderate_stress_body", PracticeId.BODY_AWARENESS, 4, _moderate_stress),
    Modifier("moderate_stress_thought", PracticeId.THOUGHT_OBSERVATION, -6, _moderate_stress),
    # The kindness window.
    Modifier(
        "kindness_window",
        PracticeId.KINDNESS,
        30,
        _kindness_window,
        (ReasonCode.SELF_DIRECTED_CARE,),
    ),
    # A busy mind: ground it, or watch it deliberately.
    Modifier(
        "busy_mind_body",
        PracticeId.BODY_AWARENESS,
        12,
        lambda s: s.high_mental_activity,
        (ReasonCode.HIGH_MENTAL_ACTIVITY,),
    ),
    Modifier(
        "busy_mind_thought",
        PracticeId.THOUGHT_OBSERVATION,
        14,
        lambda s: s.high_mental_activity,
        (ReasonCode.COGNITIVE_OBSERVATION,),
    ),
    Modifier("busy_mind_breath", PracticeId.BREATH_AWARENESS, 2, lambda s: s.high_mental_activity),
    Modifier("busy_mind_feeling", PracticeId.FEELING_TONE, 6, lambda s: s.high_mental_activity),
    Modifier("busy_mind_walking", PracticeId.MINDFUL_WALKING, 4, lambda s: s.high_mental_activity),
    Modifier("busy_mind_open", PracticeId.OPEN_AWARENESS, -8, lambda s: s.high_mental_activity),
    # Watching thoughts needs thoughts worth watching.
    Modifier(
        "quiet_mind_thought",
        PracticeId.THOUGHT_OBSERVATION,
        -10,
        lambda s: not s.high_mental_activity,
    ),
    # Sleepiness: the body holds attention when alertness is low.
    Modifier(
        "sleepy_body",
        PracticeId.BODY_AWARENESS,
        16,
        lambda s: s.high_sleepiness,
        (ReasonCode.HIGH_SLEEPINESS,),
    ),
    Modifier("sleepy_open", PracticeId.OPEN_AWARENESS, -10, lambda s: s.high_sleepiness),
    # Energy. This is what makes the field load-bearing (SDD_PROGRAM002 2.1).
    Modifier(
        "high_energy_walking",
        PracticeId.MINDFUL_WALKING,
        20,
        _walking_window,
        (ReasonCode.HIGH_ENERGY,),
    ),
    Modifier(
        "movement_preferred",
        PracticeId.MINDFUL_WALKING,
        10,
        _walking_window,
        (ReasonCode.MOVEMENT_PREFERRED,),
    ),
    Modifier("low_energy_walking", PracticeId.MINDFUL_WALKING, -20, lambda s: s.low_energy, ()),
    Modifier(
        "low_energy_body",
        PracticeId.BODY_AWARENESS,
        6,
        lambda s: s.low_energy,
        (ReasonCode.LOW_ENERGY,),
    ),
    # Experience shapes ranking; eligibility floors are handled separately.
    Modifier(
        "beginner_thought",
        PracticeId.THOUGHT_OBSERVATION,
        -4,
        lambda s: s.experience_level is ExperienceLevel.BEGINNER,
    ),
    Modifier(
        "beginner_feeling",
        PracticeId.FEELING_TONE,
        -6,
        lambda s: s.experience_level is ExperienceLevel.BEGINNER,
    ),
    Modifier(
        "intermediate_feeling",
        PracticeId.FEELING_TONE,
        6,
        lambda s: s.experience_level is ExperienceLevel.INTERMEDIATE,
    ),
    Modifier(
        "intermediate_general_body",
        PracticeId.BODY_AWARENESS,
        6,
        lambda s: s.experience_level is ExperienceLevel.INTERMEDIATE and s.goal is Goal.GENERAL,
        (ReasonCode.EXPERIENCE_PROGRESSION,),
    ),
    Modifier(
        "experienced_open",
        PracticeId.OPEN_AWARENESS,
        15,
        lambda s: s.experience_level is ExperienceLevel.EXPERIENCED,
        (ReasonCode.EXPERIENCE_PROGRESSION,),
    ),
    Modifier(
        "experienced_thought",
        PracticeId.THOUGHT_OBSERVATION,
        5,
        lambda s: s.experience_level is ExperienceLevel.EXPERIENCED,
    ),
    Modifier(
        "experienced_breath",
        PracticeId.BREATH_AWARENESS,
        -2,
        lambda s: s.experience_level is ExperienceLevel.EXPERIENCED,
    ),
    Modifier(
        "settled_experienced_open",
        PracticeId.OPEN_AWARENESS,
        12,
        lambda s: s.goal is Goal.STRESS
        and not s.moderate_stress
        and s.experience_level is ExperienceLevel.EXPERIENCED,
        (ReasonCode.EXPERIENCED_OPEN_AWARENESS,),
    ),
)

# Reason codes each goal may emit under v2.
ALLOWED_REASON_CODES_V2: dict[Goal, frozenset[ReasonCode]] = {
    goal: frozenset(
        {GOAL_REASON_CODE[goal]}
        | {code for modifier in MODIFIERS for code in modifier.reason_codes}
    )
    for goal in Goal
}


def evaluate(state: StateVector, catalog: KnowledgeCatalog) -> RuleOutcome:
    """Score every eligible practice for this state."""
    affinity = BASE_AFFINITY[state.goal]
    goal_code = GOAL_REASON_CODE[state.goal]

    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []

    for practice_id in PRACTICE_ORDER:
        if not catalog.has_executable_protocol(practice_id.value):
            exclusions.append(Exclusion(practice_id, "no_executable_protocol"))
            continue
        practice = catalog.practice(practice_id.value)
        if practice.is_contraindicated_for(state):
            exclusions.append(Exclusion(practice_id, "contraindicated"))
            continue
        if not practice.meets_experience_floor(state.experience_level):
            exclusions.append(Exclusion(practice_id, "below_minimum_experience"))
            continue

        score = affinity.get(practice_id, 0)
        codes: list[ReasonCode] = [goal_code]
        for modifier in MODIFIERS:
            if modifier.practice is practice_id and modifier.predicate(state):
                score += modifier.delta
                codes.extend(modifier.reason_codes)

        deduped = tuple(dict.fromkeys(codes))
        candidates.append(Candidate(practice_id, clamp_score(score), deduped))

    candidates.sort(key=lambda c: (-c.score, PRACTICE_INDEX[c.practice_id]))
    return RuleOutcome(
        candidates=tuple(candidates),
        exclusions=tuple(exclusions),
        rule_set_version=RuleSetVersion.V2.value,
    )
