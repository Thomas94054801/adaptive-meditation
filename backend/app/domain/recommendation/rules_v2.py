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
        PracticeId.KINDNESS: 50,
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

    ``goals`` scopes the modifier. An unscoped modifier applies to every goal,
    which is almost always wrong: sleepiness is a problem when the user wants
    focus and the point of the session when they want sleep. The first
    comparator run caught exactly that - unscoped sleepiness and energy
    modifiers pushed body_awareness to 76% of all states.

    A zero delta with a reason code is an explanation-only modifier: it changes
    no ranking and exists so a recommendation that v1 already made keeps the
    wording v1 gave it.
    """

    name: str
    practice: PracticeId
    delta: int
    predicate: Callable[[StateVector], bool]
    reason_codes: tuple[ReasonCode, ...] = field(default=())
    goals: frozenset[Goal] | None = None

    def applies_to(self, state: StateVector) -> bool:
        if self.goals is not None and state.goal not in self.goals:
            return False
        return self.predicate(state)


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
    # --- stress ---------------------------------------------------------------
    # Very high stress grounds, where stress is the presenting problem. Scoped:
    # applying it everywhere made body_awareness win 69% of all states.
    Modifier(
        "very_high_stress_body",
        PracticeId.BODY_AWARENESS,
        20,
        lambda s: s.very_high_stress,
        (ReasonCode.VERY_HIGH_STRESS,),
        frozenset({Goal.STRESS, Goal.SLEEP}),
    ),
    Modifier(
        "very_high_stress_breath",
        PracticeId.BREATH_AWARENESS,
        5,
        lambda s: s.very_high_stress,
        (),
        frozenset({Goal.STRESS}),
    ),
    Modifier(
        "very_high_stress_thought",
        PracticeId.THOUGHT_OBSERVATION,
        -15,
        lambda s: s.very_high_stress,
        (),
        frozenset({Goal.STRESS}),
    ),
    Modifier(
        "very_high_stress_open",
        PracticeId.OPEN_AWARENESS,
        -15,
        lambda s: s.very_high_stress,
        (),
        frozenset({Goal.STRESS}),
    ),
    # Moderate stress: the breath is the steadiest single anchor.
    Modifier(
        "moderate_stress_breath",
        PracticeId.BREATH_AWARENESS,
        6,
        _moderate_stress,
        (ReasonCode.MODERATE_STRESS,),
        frozenset({Goal.STRESS}),
    ),
    Modifier(
        "moderate_stress_body",
        PracticeId.BODY_AWARENESS,
        4,
        _moderate_stress,
        (),
        frozenset({Goal.STRESS}),
    ),
    Modifier(
        "moderate_stress_thought",
        PracticeId.THOUGHT_OBSERVATION,
        -6,
        _moderate_stress,
        (),
        frozenset({Goal.STRESS}),
    ),
    # Declared change: stress in 5..7 with a racing mind grounds rather than
    # anchoring on the breath.
    Modifier(
        "stress_busy_body",
        PracticeId.BODY_AWARENESS,
        12,
        lambda s: _moderate_stress(s) and s.high_mental_activity,
        (ReasonCode.HIGH_MENTAL_ACTIVITY,),
        frozenset({Goal.STRESS}),
    ),
    Modifier(
        "settled_experienced_open",
        PracticeId.OPEN_AWARENESS,
        12,
        lambda s: not s.moderate_stress and s.experience_level is ExperienceLevel.EXPERIENCED,
        (ReasonCode.EXPERIENCED_OPEN_AWARENESS,),
        frozenset({Goal.STRESS}),
    ),
    # --- overthinking ---------------------------------------------------------
    # A racing mind under pressure grounds; a racing mind alone is watched.
    Modifier(
        "overthinking_pressure_body",
        PracticeId.BODY_AWARENESS,
        20,
        lambda s: s.high_mental_activity and s.elevated_stress,
        (ReasonCode.HIGH_MENTAL_ACTIVITY, ReasonCode.HIGH_STRESS),
        frozenset({Goal.OVERTHINKING}),
    ),
    Modifier(
        "overthinking_watch_thought",
        PracticeId.THOUGHT_OBSERVATION,
        14,
        lambda s: s.high_mental_activity and not s.elevated_stress,
        (ReasonCode.HIGH_MENTAL_ACTIVITY, ReasonCode.COGNITIVE_OBSERVATION),
        frozenset({Goal.OVERTHINKING}),
    ),
    # Watching thoughts needs thoughts worth watching.
    Modifier(
        "quiet_mind_thought",
        PracticeId.THOUGHT_OBSERVATION,
        -10,
        lambda s: not s.high_mental_activity,
        (),
        frozenset({Goal.OVERTHINKING}),
    ),
    # --- sleep ----------------------------------------------------------------
    Modifier(
        "sleep_busy_body",
        PracticeId.BODY_AWARENESS,
        12,
        lambda s: s.high_mental_activity,
        (ReasonCode.HIGH_MENTAL_ACTIVITY,),
        frozenset({Goal.SLEEP}),
    ),
    # Explanation-only: zero delta, so no ranking moves. Keeps the wording v1
    # gave a recommendation v2 still makes.
    Modifier(
        "sleep_grounding",
        PracticeId.BODY_AWARENESS,
        0,
        lambda s: True,
        (ReasonCode.GROUNDING_PREFERRED,),
        frozenset({Goal.SLEEP}),
    ),
    # --- focus ----------------------------------------------------------------
    # Sleepiness is an obstacle here and the point of the session elsewhere.
    # 18, not 16: at 16 this tied with breath_awareness when low energy also
    # applied, and the tie-break handed sleepy focus sessions to the breath.
    # Sleepiness is the stronger signal for this goal, so it must not tie.
    Modifier(
        "sleepy_body",
        PracticeId.BODY_AWARENESS,
        18,
        lambda s: s.high_sleepiness,
        (ReasonCode.HIGH_SLEEPINESS,),
        frozenset({Goal.FOCUS}),
    ),
    Modifier(
        "sleepy_open",
        PracticeId.OPEN_AWARENESS,
        -10,
        lambda s: s.high_sleepiness,
        (),
        frozenset({Goal.FOCUS}),
    ),
    # The energy rule, in both directions. This is what makes the field
    # load-bearing, and it is falsifiable: change energy alone and the
    # recommendation changes.
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
    Modifier(
        "low_energy_walking",
        PracticeId.MINDFUL_WALKING,
        -20,
        lambda s: s.low_energy,
        (),
        frozenset({Goal.FOCUS}),
    ),
    Modifier(
        "low_energy_breath",
        PracticeId.BREATH_AWARENESS,
        4,
        lambda s: s.low_energy,
        (ReasonCode.LOW_ENERGY,),
        frozenset({Goal.FOCUS}),
    ),
    Modifier(
        "focus_stabilize",
        PracticeId.BREATH_AWARENESS,
        0,
        lambda s: True,
        (ReasonCode.STABILIZE_ATTENTION,),
        frozenset({Goal.FOCUS}),
    ),
    # --- emotional reset ------------------------------------------------------
    Modifier(
        "kindness_window",
        PracticeId.KINDNESS,
        30,
        _kindness_window,
        (ReasonCode.SELF_DIRECTED_CARE,),
    ),
    Modifier(
        "reset_reactivity",
        PracticeId.FEELING_TONE,
        0,
        lambda s: True,
        (ReasonCode.RECOGNIZE_REACTIVITY,),
        frozenset({Goal.EMOTIONAL_RESET}),
    ),
    # --- experience -----------------------------------------------------------
    # Ranking only; eligibility floors are hard filters handled before scoring.
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
        lambda s: s.experience_level is ExperienceLevel.INTERMEDIATE,
        (ReasonCode.EXPERIENCE_PROGRESSION,),
        frozenset({Goal.GENERAL}),
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
            if modifier.practice is practice_id and modifier.applies_to(state):
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
