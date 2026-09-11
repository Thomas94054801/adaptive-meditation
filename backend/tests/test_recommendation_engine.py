"""Recommendation engine tests - SDD section 15.1.

The numbered cases below are the SDD's required matrix, kept in its order so a
reviewer can check them off one for one.
"""

from __future__ import annotations

import itertools

import pytest

from app.domain.practice.catalog import KnowledgeCatalog, KnowledgeValidationError
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.recommendation.rules import (
    ALLOWED_REASON_CODES,
    RULES_VERSION,
    PracticeId,
    ReasonCode,
    select_practice,
)
from app.domain.state.models import (
    AVAILABLE_MINUTES,
    CheckIn,
    ExperienceLevel,
    Goal,
    StateVector,
)

# Practices the V1 rules can actually select. kindness is declared in the
# knowledge files and has an executable protocol, but no rule reaches it yet;
# that is Program002 work and is asserted here so it cannot become a silent gap.
REACHABLE_PRACTICES = frozenset(
    {
        PracticeId.BREATH_AWARENESS,
        PracticeId.BODY_AWARENESS,
        PracticeId.FEELING_TONE,
        PracticeId.THOUGHT_OBSERVATION,
        PracticeId.OPEN_AWARENESS,
    }
)
DECLARED_BUT_UNREACHABLE = frozenset({PracticeId.KINDNESS})


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


# --- 15.1 required cases ------------------------------------------------------


def test_case_1_overthinking_high_activity_high_stress(engine: RecommendationEngine) -> None:
    """goal=overthinking, mental_activity=9, stress=8 -> body_awareness."""
    result = engine.recommend(make_check_in(goal="overthinking", mental_activity=9, stress=8))
    assert result.practice_id == "body_awareness"
    assert result.reason_codes == ("goal_overthinking", "high_mental_activity", "high_stress")
    assert result.recommendation_version == RULES_VERSION


def test_case_2_overthinking_high_activity_low_stress(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="overthinking", mental_activity=9, stress=3))
    assert result.practice_id == "thought_observation"
    assert result.reason_codes == (
        "goal_overthinking",
        "high_mental_activity",
        "cognitive_observation",
    )


def test_case_3_sleep(engine: RecommendationEngine) -> None:
    for mental_activity in range(11):
        result = engine.recommend(make_check_in(goal="sleep", mental_activity=mental_activity))
        assert result.practice_id == "body_awareness"
        assert "goal_sleep" in result.reason_codes
        assert "grounding_preferred" in result.reason_codes


def test_case_4_focus_high_sleepiness(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="focus", sleepiness=8))
    assert result.practice_id == "body_awareness"
    assert result.reason_codes == ("goal_focus", "high_sleepiness")


def test_case_5_focus_low_sleepiness(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="focus", sleepiness=2))
    assert result.practice_id == "breath_awareness"
    assert result.reason_codes == ("goal_focus", "stabilize_attention")


def test_case_6_stress_very_high(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="stress", stress=9))
    assert result.practice_id == "body_awareness"
    assert result.reason_codes == ("goal_stress", "very_high_stress")


def test_case_7_stress_low_experienced(engine: RecommendationEngine) -> None:
    result = engine.recommend(
        make_check_in(goal="stress", stress=2, experience_level="experienced")
    )
    assert result.practice_id == "open_awareness"
    assert result.reason_codes == ("goal_stress", "experienced_open_awareness")


def test_case_8_general_beginner(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="general", experience_level="beginner"))
    assert result.practice_id == "breath_awareness"
    assert result.reason_codes == ("goal_general",)


def test_case_9_general_experienced(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="general", experience_level="experienced"))
    assert result.practice_id == "open_awareness"
    assert result.reason_codes == ("goal_general", "experience_progression")


def test_case_10_repeated_input_is_identical(engine: RecommendationEngine) -> None:
    """Same normalized input, 100 times, byte-identical output."""
    check_in = make_check_in(goal="overthinking", mental_activity=9, stress=8)
    first = engine.recommend(check_in)
    serialized = first.model_dump_json()
    for _ in range(100):
        assert engine.recommend(check_in).model_dump_json() == serialized


# --- additional rule coverage -------------------------------------------------


def test_stress_moderate_band(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="stress", stress=6))
    assert result.practice_id == "breath_awareness"
    assert result.reason_codes == ("goal_stress", "moderate_stress")


def test_stress_low_non_experienced_stays_with_breath(engine: RecommendationEngine) -> None:
    for level in (ExperienceLevel.BEGINNER, ExperienceLevel.INTERMEDIATE):
        result = engine.recommend(
            make_check_in(goal="stress", stress=1, experience_level=level.value)
        )
        assert result.practice_id == "breath_awareness"
        assert result.reason_codes == ("goal_stress",)


def test_overthinking_low_activity_uses_breath(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="overthinking", mental_activity=3, stress=9))
    assert result.practice_id == "breath_awareness"
    assert result.reason_codes == ("goal_overthinking",)


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("beginner", "body_awareness"),
        ("intermediate", "feeling_tone"),
        ("experienced", "feeling_tone"),
    ],
)
def test_emotional_reset_by_experience(
    engine: RecommendationEngine, level: str, expected: str
) -> None:
    result = engine.recommend(make_check_in(goal="emotional_reset", experience_level=level))
    assert result.practice_id == expected


def test_general_intermediate(engine: RecommendationEngine) -> None:
    result = engine.recommend(make_check_in(goal="general", experience_level="intermediate"))
    assert result.practice_id == "body_awareness"


# --- invariants over the whole reachable input space --------------------------


def iter_states() -> list[StateVector]:
    """Every combination of the dimensions the rules actually read.

    energy is not read by any V1 rule, so it is pinned rather than crossed; the
    ``test_energy_does_not_change_the_outcome`` case below proves that claim
    instead of assuming it.
    """
    states = []
    for goal, stress, mental_activity, sleepiness, minutes, level in itertools.product(
        Goal, range(11), range(11), range(11), AVAILABLE_MINUTES, ExperienceLevel
    ):
        states.append(
            StateVector(
                goal=goal,
                experience_level=level,
                available_minutes=minutes,  # type: ignore[arg-type]
                stress=stress,
                energy=5,
                mental_activity=mental_activity,
                sleepiness=sleepiness,
            )
        )
    return states


@pytest.fixture(scope="module")
def all_states() -> list[StateVector]:
    return iter_states()


def test_every_state_produces_a_known_practice(
    engine: RecommendationEngine, catalog: KnowledgeCatalog, all_states: list[StateVector]
) -> None:
    """15.5: the engine must never return a practice_id the catalog does not know."""
    known = set(catalog.practice_ids())
    for state in all_states:
        result = engine.recommend_for_state(state)
        assert result.practice_id in known


def test_reason_codes_stay_inside_the_goal_vocabulary(
    engine: RecommendationEngine, all_states: list[StateVector]
) -> None:
    for state in all_states:
        allowed = {code.value for code in ALLOWED_REASON_CODES[state.goal]}
        result = engine.recommend_for_state(state)
        assert result.reason_codes[0] == f"goal_{state.goal.value}"
        assert set(result.reason_codes) <= allowed
        assert len(set(result.reason_codes)) == len(result.reason_codes)


def test_guidance_density_always_inside_the_protocol_range(
    engine: RecommendationEngine, catalog: KnowledgeCatalog, all_states: list[StateVector]
) -> None:
    """15.5: density must never fall outside the selected protocol's declared range."""
    for state in all_states:
        result = engine.recommend_for_state(state)
        protocol = catalog.protocol_for(result.practice_id)
        low, high = protocol.guidance_density_range
        assert low <= result.guidance_density <= high
        assert round(result.guidance_density, 2) == result.guidance_density


def test_duration_never_exceeds_available_minutes(
    engine: RecommendationEngine, all_states: list[StateVector]
) -> None:
    for state in all_states:
        result = engine.recommend_for_state(state)
        assert result.duration_minutes <= state.available_minutes


def test_energy_does_not_change_the_outcome(engine: RecommendationEngine) -> None:
    """energy is collected for future rules; no V1 rule may depend on it."""
    for goal in Goal:
        base = make_check_in(goal=goal.value, energy=0)
        expected = engine.recommend(base).model_dump_json()
        for energy in range(1, 11):
            other = make_check_in(goal=goal.value, energy=energy)
            assert engine.recommend(other).model_dump_json() == expected


def test_reachable_practice_set_is_exactly_as_documented(all_states: list[StateVector]) -> None:
    reached = {select_practice(state).primary for state in all_states}
    assert reached == REACHABLE_PRACTICES
    assert reached.isdisjoint(DECLARED_BUT_UNREACHABLE)


def test_identical_fingerprints_give_identical_recommendations(
    engine: RecommendationEngine, all_states: list[StateVector]
) -> None:
    seen: dict[str, str] = {}
    for state in all_states:
        result = engine.recommend_for_state(state).model_dump_json()
        fingerprint = state.fingerprint()
        assert seen.setdefault(fingerprint, result) == result


# --- fallback resolution ------------------------------------------------------


def test_sleep_declares_a_fallback_when_mental_activity_is_high() -> None:
    state = StateVector(
        goal=Goal.SLEEP,
        experience_level=ExperienceLevel.BEGINNER,
        available_minutes=10,
        stress=4,
        energy=5,
        mental_activity=9,
        sleepiness=4,
    )
    selection = select_practice(state)
    assert selection.primary is PracticeId.BODY_AWARENESS
    assert selection.fallback is PracticeId.BREATH_AWARENESS


def test_fallback_is_used_and_reported_when_the_primary_has_no_protocol(
    catalog: KnowledgeCatalog,
) -> None:
    """Falling back is never silent: it adds a reason code."""
    reduced = KnowledgeCatalog(
        practices={
            key: value for key, value in catalog.practices.items() if key != "body_awareness"
        },
        protocols_by_practice={
            key: value
            for key, value in catalog.protocols_by_practice.items()
            if key != "body_awareness"
        },
        practices_schema_version=catalog.practices_schema_version,
        protocols_schema_version=catalog.protocols_schema_version,
    )
    result = RecommendationEngine(reduced).recommend(make_check_in(goal="sleep", mental_activity=9))
    assert result.practice_id == "breath_awareness"
    assert ReasonCode.FALLBACK_PRACTICE_USED.value in result.reason_codes


def test_missing_practice_without_fallback_is_an_error(catalog: KnowledgeCatalog) -> None:
    reduced = KnowledgeCatalog(
        practices={
            key: value for key, value in catalog.practices.items() if key != "open_awareness"
        },
        protocols_by_practice={
            key: value
            for key, value in catalog.protocols_by_practice.items()
            if key != "open_awareness"
        },
        practices_schema_version=catalog.practices_schema_version,
        protocols_schema_version=catalog.protocols_schema_version,
    )
    with pytest.raises(KnowledgeValidationError):
        RecommendationEngine(reduced).recommend(
            make_check_in(goal="general", experience_level="experienced")
        )
