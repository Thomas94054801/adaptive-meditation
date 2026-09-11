"""V1 replay.

Rule set v1 on knowledge v1 must keep producing exactly what Program001 served,
forever. Stored recommendations carry a rule_set_version; if that version stops
being replayable, every one of those records becomes unreadable evidence.

This file is the frozen Program001 matrix (SDD_PROGRAM001 section 15.1). It runs
against ``engine_v1`` and must never be updated to match a v2 behaviour change.
"""

from __future__ import annotations

import pytest

from app.domain.recommendation.engine import Recommendation, RecommendationEngine
from app.domain.recommendation.versions import LEGACY_ENGINE_VERSION
from app.domain.state.models import CheckIn


def check_in(**overrides: object) -> CheckIn:
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


# The exact Program001 expectations: practice and reason codes, in order.
V1_MATRIX: list[tuple[str, dict[str, object], str, tuple[str, ...]]] = [
    (
        "case_1_overthinking_high_activity_high_stress",
        {"goal": "overthinking", "mental_activity": 9, "stress": 8},
        "body_awareness",
        ("goal_overthinking", "high_mental_activity", "high_stress"),
    ),
    (
        "case_2_overthinking_high_activity_low_stress",
        {"goal": "overthinking", "mental_activity": 9, "stress": 3},
        "thought_observation",
        ("goal_overthinking", "high_mental_activity", "cognitive_observation"),
    ),
    (
        "case_3_sleep",
        {"goal": "sleep"},
        "body_awareness",
        ("goal_sleep", "grounding_preferred"),
    ),
    (
        "case_4_focus_high_sleepiness",
        {"goal": "focus", "sleepiness": 8},
        "body_awareness",
        ("goal_focus", "high_sleepiness"),
    ),
    (
        "case_5_focus_low_sleepiness",
        {"goal": "focus", "sleepiness": 2},
        "breath_awareness",
        ("goal_focus", "stabilize_attention"),
    ),
    (
        "case_6_stress_very_high",
        {"goal": "stress", "stress": 9},
        "body_awareness",
        ("goal_stress", "very_high_stress"),
    ),
    (
        "case_7_stress_low_experienced",
        {"goal": "stress", "stress": 2, "experience_level": "experienced"},
        "open_awareness",
        ("goal_stress", "experienced_open_awareness"),
    ),
    (
        "case_8_general_beginner",
        {"goal": "general", "experience_level": "beginner"},
        "breath_awareness",
        ("goal_general",),
    ),
    (
        "case_9_general_experienced",
        {"goal": "general", "experience_level": "experienced"},
        "open_awareness",
        ("goal_general", "experience_progression"),
    ),
]


@pytest.mark.parametrize(
    ("name", "overrides", "practice", "codes"),
    V1_MATRIX,
    ids=[row[0] for row in V1_MATRIX],
)
def test_v1_matrix_is_unchanged(
    engine_v1: RecommendationEngine,
    name: str,
    overrides: dict[str, object],
    practice: str,
    codes: tuple[str, ...],
) -> None:
    result = engine_v1.recommend(check_in(**overrides))
    assert result.practice_id == practice
    assert result.reason_codes == codes
    assert result.rule_set_version == "1"


def test_v1_case_10_repeated_input_is_identical(engine_v1: RecommendationEngine) -> None:
    subject = check_in(goal="overthinking", mental_activity=9, stress=8)
    serialized = engine_v1.recommend(subject).model_dump_json()
    for _ in range(100):
        assert engine_v1.recommend(subject).model_dump_json() == serialized


def test_v1_sleep_is_body_awareness_at_every_mental_activity(
    engine_v1: RecommendationEngine,
) -> None:
    for mental_activity in range(11):
        result = engine_v1.recommend(check_in(goal="sleep", mental_activity=mental_activity))
        assert result.practice_id == "body_awareness"


def test_v1_never_reaches_the_v2_practices(engine_v1: RecommendationEngine) -> None:
    """kindness and mindful_walking were unreachable under v1. That is the gap v2 closed."""
    from tests.test_recommendation_engine import iter_states

    reached = {engine_v1.recommend_for_state(state).practice_id for state in iter_states(sample=7)}
    assert "kindness" not in reached
    assert "mindful_walking" not in reached


# --- stored v1 records stay readable -----------------------------------------

LEGACY_ROW = {
    "practice_id": "body_awareness",
    "duration_minutes": 10,
    "guidance_density": 0.7,
    "reason_codes": ["goal_overthinking", "high_mental_activity", "high_stress"],
    "recommendation_version": "1",
}


def test_a_program001_row_still_loads() -> None:
    """A row written before engine_version existed must not need migrating."""
    stored = Recommendation.from_stored(LEGACY_ROW)
    assert stored.practice_id == "body_awareness"
    assert stored.duration_minutes == 10
    assert stored.guidance_density == 0.7
    assert stored.engine_version == LEGACY_ENGINE_VERSION
    assert stored.rule_set_version == "1"
    assert stored.protocol_version == "1"
    assert stored.state_fingerprint == ""


def test_a_v2_row_round_trips(engine: RecommendationEngine) -> None:
    current = engine.recommend(check_in(goal="focus", energy=9, stress=4))
    assert Recommendation.from_stored(current.model_dump(mode="json")) == current


def test_replaying_a_stored_v1_row_reproduces_it(engine_v1: RecommendationEngine) -> None:
    """The point of keeping v1 runnable: the row can be re-derived, not just read."""
    stored = Recommendation.from_stored(LEGACY_ROW)
    replayed = engine_v1.recommend(check_in(goal="overthinking", mental_activity=9, stress=8))
    assert replayed.practice_id == stored.practice_id
    assert replayed.duration_minutes == stored.duration_minutes
    assert replayed.guidance_density == stored.guidance_density
    assert replayed.reason_codes == tuple(stored.reason_codes)
