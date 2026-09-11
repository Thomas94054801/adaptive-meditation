"""Duration policy tests - SDD section 15.2.

Every available_minutes / experience_level combination, stated explicitly rather
than recomputed from the table under test.
"""

from __future__ import annotations

import pytest

from app.domain.recommendation.engine import RecommendationEngine
from app.domain.recommendation.rules import select_duration
from app.domain.state.models import AVAILABLE_MINUTES, ExperienceLevel, Goal, StateVector

EXPECTED: dict[tuple[int, str], int] = {
    (3, "beginner"): 3,
    (3, "intermediate"): 3,
    (3, "experienced"): 3,
    (5, "beginner"): 5,
    (5, "intermediate"): 5,
    (5, "experienced"): 5,
    (10, "beginner"): 10,
    (10, "intermediate"): 10,
    (10, "experienced"): 10,
    (15, "beginner"): 10,
    (15, "intermediate"): 15,
    (15, "experienced"): 15,
    (20, "beginner"): 10,
    (20, "intermediate"): 15,
    (20, "experienced"): 20,
}


def state(minutes: int, level: str, goal: Goal = Goal.GENERAL) -> StateVector:
    return StateVector(
        goal=goal,
        experience_level=ExperienceLevel(level),
        available_minutes=minutes,  # type: ignore[arg-type]
        stress=5,
        energy=5,
        mental_activity=5,
        sleepiness=5,
    )


@pytest.mark.parametrize(("minutes", "level"), sorted(EXPECTED))
def test_every_combination(engine: RecommendationEngine, minutes: int, level: str) -> None:
    expected = EXPECTED[(minutes, level)]
    assert select_duration(state(minutes, level), AVAILABLE_MINUTES) == expected
    for goal in Goal:
        result = engine.recommend_for_state(state(minutes, level, goal))
        assert result.duration_minutes == expected
        assert result.duration_minutes <= minutes


def test_policy_clamps_down_to_what_a_protocol_supports() -> None:
    """A protocol offering fewer durations steps the policy down, never up."""
    assert select_duration(state(20, "experienced"), (3, 5, 10)) == 10
    assert select_duration(state(15, "intermediate"), (3, 5)) == 5


def test_policy_raises_when_nothing_short_enough_exists() -> None:
    with pytest.raises(ValueError, match="protocol supports"):
        select_duration(state(3, "beginner"), (5, 10))
