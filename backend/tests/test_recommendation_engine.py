"""Rule set v2: golden cases and invariants over the full state space.

The Program001 matrix lives in ``test_v1_replay.py`` and is not repeated here;
v2 is a deliberate change and asserting v1's answers against it would be wrong.
The four v2 golden cases are SDD_PROGRAM002 section 3.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.recommendation.rules_v2 import (
    ALLOWED_REASON_CODES_V2,
    BASE_AFFINITY,
    MODIFIERS,
    PRACTICE_ORDER,
)
from app.domain.recommendation.scoring import SCORE_MAX, SCORE_MIN
from app.domain.recommendation.versions import ENGINE_VERSION
from app.domain.state.models import (
    AVAILABLE_MINUTES,
    CheckIn,
    ExperienceLevel,
    Goal,
    StateVector,
)

# Every practice the v2 rules must be able to reach. Program001 left kindness
# unreachable and had no mindful_walking at all; both are closed here.
EXPECTED_REACHABLE = {
    "breath_awareness",
    "body_awareness",
    "feeling_tone",
    "thought_observation",
    "kindness",
    "open_awareness",
    "mindful_walking",
}


def make_check_in(**overrides: object) -> CheckIn:
    payload: dict[str, object] = {
        "goal": "general",
        "stress": 5,
        "energy": 5,
        "mental_activity": 5,
        "sleepiness": 5,
        "available_minutes": 10,
        "experience_level": "beginner",
    }
    payload.update(overrides)
    return CheckIn.model_validate(payload)


def iter_states(sample: int = 1) -> Iterator[StateVector]:
    """The reachable state space, optionally thinned by ``sample``.

    ``sample=1`` is the full 1,317,690-state enumeration, including energy 0..10.
    Program001 pinned energy because no rule read it; v2 does, so pinning it
    would describe a space the rules do not live in.

    Thinning is by stride over the scale axes, never by random choice, so a
    thinned run is as reproducible as a full one.
    """
    scale = range(0, 11, sample)
    for goal, stress, energy, mental, sleepy, minutes, level in itertools.product(
        Goal, scale, scale, scale, scale, AVAILABLE_MINUTES, ExperienceLevel
    ):
        yield StateVector(
            goal=goal,
            experience_level=level,
            available_minutes=minutes,  # type: ignore[arg-type]
            stress=stress,
            energy=energy,
            mental_activity=mental,
            sleepiness=sleepy,
        )


FULL_STATE_SPACE_SIZE = 6 * 11 * 11 * 11 * 11 * 5 * 3  # 1,317,690


@pytest.fixture(scope="module")
def sampled_states() -> list[StateVector]:
    """A strided sample, for the invariants that are too slow over the full space."""
    return list(iter_states(sample=2))


# --- SDD_PROGRAM002 section 3: golden cases ----------------------------------


def test_golden_a_v1_behaviour_preserved(engine: RecommendationEngine) -> None:
    """goal=overthinking, mental_activity=9, stress=8 -> body_awareness."""
    result = engine.recommend(make_check_in(goal="overthinking", mental_activity=9, stress=8))
    assert result.practice_id == "body_awareness"
    # Identical to v1, codes included: see test_v1_replay for the v1 side.
    assert result.reason_codes == ("goal_overthinking", "high_mental_activity", "high_stress")


def test_golden_b_kindness_is_reachable(engine: RecommendationEngine) -> None:
    """goal=emotional_reset, stress=7, mental_activity=4 -> kindness."""
    result = engine.recommend(make_check_in(goal="emotional_reset", stress=7, mental_activity=4))
    assert result.practice_id == "kindness"
    assert "self_directed_care" in result.reason_codes


def test_golden_c_energy_is_load_bearing(engine: RecommendationEngine) -> None:
    """goal=focus, energy=9, stress=4, available_minutes=10 -> mindful_walking."""
    result = engine.recommend(make_check_in(goal="focus", energy=9, stress=4, available_minutes=10))
    assert result.practice_id == "mindful_walking"
    assert "high_energy" in result.reason_codes


def test_golden_d_open_awareness_eligible(engine: RecommendationEngine) -> None:
    """goal=general, experienced, stress=2, mental_activity=3 -> open_awareness."""
    state = StateVector.from_check_in(
        make_check_in(goal="general", experience_level="experienced", stress=2, mental_activity=3)
    )
    outcome = engine.evaluate(state)
    eligible = {candidate.practice_id.value for candidate in outcome.candidates}
    assert "open_awareness" in eligible
    assert outcome.winner.practice_id.value == "open_awareness"


# --- energy sensitivity -------------------------------------------------------


def test_lowering_energy_alone_changes_the_recommendation(engine: RecommendationEngine) -> None:
    """The falsifiable half of the energy rule.

    If energy could be removed without changing an answer, it would be a dead
    input again, which is the Program001 gap this closes.
    """
    high = engine.recommend(make_check_in(goal="focus", energy=9, stress=4))
    low = engine.recommend(make_check_in(goal="focus", energy=2, stress=4))
    assert high.practice_id == "mindful_walking"
    assert low.practice_id == "breath_awareness"
    assert "low_energy" in low.reason_codes


def test_energy_threshold_is_where_it_is_declared(engine: RecommendationEngine) -> None:
    for energy in range(11):
        result = engine.recommend(make_check_in(goal="focus", energy=energy, stress=4))
        expected = "mindful_walking" if energy >= 7 else "breath_awareness"
        assert result.practice_id == expected, energy


def test_energy_is_scoped_to_focus(engine: RecommendationEngine) -> None:
    """Outside focus, energy carries no declared meaning and must not move anything."""
    for goal in Goal:
        if goal is Goal.FOCUS:
            continue
        baseline = engine.recommend(make_check_in(goal=goal.value, energy=0)).practice_id
        for energy in range(1, 11):
            other = engine.recommend(make_check_in(goal=goal.value, energy=energy))
            assert other.practice_id == baseline, (goal, energy)


# --- reachability -------------------------------------------------------------


def test_every_intended_practice_is_reachable(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    reached = {engine.recommend_for_state(state).practice_id for state in sampled_states}
    assert reached == EXPECTED_REACHABLE


def test_mindful_walking_is_never_offered_against_its_contraindications(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    for state in sampled_states:
        if engine.recommend_for_state(state).practice_id == "mindful_walking":
            assert state.goal is not Goal.SLEEP
            assert not state.high_sleepiness


def test_open_awareness_is_never_offered_to_a_beginner(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    for state in sampled_states:
        if state.experience_level is ExperienceLevel.BEGINNER:
            assert engine.recommend_for_state(state).practice_id != "open_awareness"


def test_an_experienced_user_can_still_get_a_basic_practice(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    """Experience adjusts ranking; it must not remove eligibility."""
    reached = {
        engine.recommend_for_state(state).practice_id
        for state in sampled_states
        if state.experience_level is ExperienceLevel.EXPERIENCED
    }
    assert {"breath_awareness", "body_awareness"} <= reached


# --- invariants over the state space -----------------------------------------


def test_state_space_cardinality_is_what_we_claim() -> None:
    """Guards the number quoted in the docs against silently drifting."""
    assert sum(1 for _ in iter_states(sample=1)) == FULL_STATE_SPACE_SIZE
    assert FULL_STATE_SPACE_SIZE == 1_317_690


def test_invariants_hold_across_the_sampled_space(
    engine: RecommendationEngine, catalog: KnowledgeCatalog, sampled_states: list[StateVector]
) -> None:
    known = set(catalog.practice_ids())
    for state in sampled_states:
        result = engine.recommend_for_state(state)

        assert result.practice_id in known
        practice = catalog.practice(result.practice_id)
        protocol = catalog.protocol_for(result.practice_id)

        assert not practice.is_contraindicated_for(state)
        assert practice.meets_experience_floor(state.experience_level)
        assert protocol.supports_duration(result.duration_minutes)
        assert result.duration_minutes <= state.available_minutes
        low, high = protocol.guidance_density_range
        assert low <= result.guidance_density <= high
        assert round(result.guidance_density, 2) == result.guidance_density

        allowed = {code.value for code in ALLOWED_REASON_CODES_V2[state.goal]}
        assert result.reason_codes[0] == f"goal_{state.goal.value}"
        assert set(result.reason_codes) <= allowed
        assert len(set(result.reason_codes)) == len(result.reason_codes)

        assert result.engine_version == ENGINE_VERSION
        assert result.rule_set_version == "2"
        assert result.state_fingerprint == state.fingerprint()


def test_identical_input_gives_identical_output(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    seen: dict[str, str] = {}
    for state in sampled_states:
        serialized = engine.recommend_for_state(state).model_dump_json()
        assert seen.setdefault(state.fingerprint(), serialized) == serialized


def test_repeating_one_input_is_stable(engine: RecommendationEngine) -> None:
    subject = make_check_in(goal="emotional_reset", stress=7, mental_activity=4)
    serialized = engine.recommend(subject).model_dump_json()
    for _ in range(100):
        assert engine.recommend(subject).model_dump_json() == serialized


# --- scoring -----------------------------------------------------------------


def test_scores_are_bounded_integers(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    for state in sampled_states:
        for candidate in engine.evaluate(state).candidates:
            assert isinstance(candidate.score, int)
            assert SCORE_MIN <= candidate.score <= SCORE_MAX


def test_candidates_are_ordered_by_score_then_declaration(
    engine: RecommendationEngine, sampled_states: list[StateVector]
) -> None:
    index = {practice: position for position, practice in enumerate(PRACTICE_ORDER)}
    for state in sampled_states:
        keys = [
            (-candidate.score, index[candidate.practice_id])
            for candidate in engine.evaluate(state).candidates
        ]
        assert keys == sorted(keys)


def test_exclusions_are_recorded_with_a_reason(engine: RecommendationEngine) -> None:
    state = StateVector.from_check_in(make_check_in(goal="sleep", sleepiness=9))
    outcome = engine.evaluate(state)
    excluded = {e.practice_id.value: e.reason for e in outcome.exclusions}
    assert excluded["mindful_walking"] == "contraindicated"
    assert excluded["open_awareness"] == "below_minimum_experience"


def test_every_goal_declares_an_affinity_for_every_practice() -> None:
    """A missing entry would score 0 silently instead of failing loudly."""
    for goal in Goal:
        assert set(BASE_AFFINITY[goal]) == set(PRACTICE_ORDER), goal


def test_modifier_names_are_unique() -> None:
    names = [modifier.name for modifier in MODIFIERS]
    assert len(set(names)) == len(names)


def test_every_modifier_is_reachable(sampled_states: list[StateVector]) -> None:
    """A modifier no state can trigger is dead weight in the rule table."""
    fired = {
        modifier.name
        for state in sampled_states
        for modifier in MODIFIERS
        if modifier.applies_to(state)
    }
    assert fired == {modifier.name for modifier in MODIFIERS}
