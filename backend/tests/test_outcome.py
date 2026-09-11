"""Outcome evidence."""

from __future__ import annotations

import pytest

from app.domain.outcome.models import (
    GOAL_MEASURES,
    SCORE_MAX,
    SCORE_MIN,
    OutcomeMeasure,
    StateSnapshot,
    compute_outcome,
    measure_delta,
    session_outcome_score,
)
from app.domain.state.models import Goal

BEFORE = StateSnapshot(stress=8, energy=3, mental_activity=9, sleepiness=2)
AFTER = StateSnapshot(stress=3, energy=6, mental_activity=4, sleepiness=5)


def test_every_goal_declares_a_measure() -> None:
    assert set(GOAL_MEASURES) == set(Goal)


@pytest.mark.parametrize(
    ("goal", "measure", "delta"),
    [
        (Goal.STRESS, OutcomeMeasure.STRESS_REDUCTION, 5),
        (Goal.OVERTHINKING, OutcomeMeasure.MENTAL_QUIETING, 5),
        (Goal.SLEEP, OutcomeMeasure.SLEEP_ONSET, 3),
        (Goal.FOCUS, OutcomeMeasure.ACTIVATION, 3),
        (Goal.EMOTIONAL_RESET, OutcomeMeasure.STRESS_REDUCTION, 5),
    ],
)
def test_goal_specific_primary_measure(goal: Goal, measure: OutcomeMeasure, delta: int) -> None:
    outcome = compute_outcome(
        goal=goal, before=BEFORE, after=AFTER, helpfulness=4, completion_ratio=1.0
    )
    assert outcome.primary_measure is measure
    assert outcome.primary_delta == delta


def test_focus_carries_a_secondary_measure() -> None:
    outcome = compute_outcome(
        goal=Goal.FOCUS, before=BEFORE, after=AFTER, helpfulness=4, completion_ratio=1.0
    )
    assert outcome.secondary_measure is OutcomeMeasure.MENTAL_QUIETING
    assert outcome.secondary_delta == 5


def test_general_uses_helpfulness_directly() -> None:
    outcome = compute_outcome(
        goal=Goal.GENERAL, before=BEFORE, after=AFTER, helpfulness=4, completion_ratio=1.0
    )
    assert outcome.primary_measure is OutcomeMeasure.GENERAL_HELPFULNESS
    assert outcome.primary_delta == 4


def test_positive_always_means_the_intended_direction() -> None:
    """Sleepiness going up is good for sleep and stress going down is good for stress."""
    worse_sleep = StateSnapshot(stress=8, energy=3, mental_activity=9, sleepiness=0)
    assert measure_delta(OutcomeMeasure.SLEEP_ONSET, BEFORE, worse_sleep, 3) == -2
    assert measure_delta(OutcomeMeasure.SLEEP_ONSET, BEFORE, AFTER, 3) == 3


def test_raw_values_are_preserved_unchanged() -> None:
    """The derived view must never replace its inputs."""
    outcome = compute_outcome(
        goal=Goal.STRESS, before=BEFORE, after=AFTER, helpfulness=4, completion_ratio=0.5
    )
    assert outcome.before == BEFORE
    assert outcome.after == AFTER
    assert outcome.as_dict()["before"] == BEFORE.as_dict()
    assert outcome.as_dict()["after"] == AFTER.as_dict()


def test_outcome_score_is_bounded() -> None:
    worst = session_outcome_score(
        primary_measure=OutcomeMeasure.STRESS_REDUCTION,
        primary_delta=-100,
        helpfulness=1,
        completion_ratio=0.0,
    )
    best = session_outcome_score(
        primary_measure=OutcomeMeasure.STRESS_REDUCTION,
        primary_delta=100,
        helpfulness=5,
        completion_ratio=1.0,
    )
    assert worst == SCORE_MIN
    assert best == SCORE_MAX


def test_outcome_score_is_monotonic_in_each_input() -> None:
    def score(delta: int = 0, helpfulness: int = 3, completion: float = 0.5) -> int:
        return session_outcome_score(
            primary_measure=OutcomeMeasure.STRESS_REDUCTION,
            primary_delta=delta,
            helpfulness=helpfulness,
            completion_ratio=completion,
        )

    assert score(delta=-5) < score(delta=0) < score(delta=5)
    assert score(helpfulness=1) < score(helpfulness=3) < score(helpfulness=5)
    assert score(completion=0.0) < score(completion=0.5) < score(completion=1.0)


def test_outcome_score_is_deterministic() -> None:
    args = {
        "primary_measure": OutcomeMeasure.STRESS_REDUCTION,
        "primary_delta": 3,
        "helpfulness": 4,
        "completion_ratio": 0.75,
    }
    first = session_outcome_score(**args)  # type: ignore[arg-type]
    for _ in range(100):
        assert session_outcome_score(**args) == first  # type: ignore[arg-type]


def test_the_score_is_documented_as_a_product_metric_only() -> None:
    """The label is part of the contract, not a comment someone can drop."""
    import app.domain.outcome.models as module

    text = (module.__doc__ or "") + (session_outcome_score.__doc__ or "")
    lowered = text.lower()
    assert "product optimization metric only" in lowered
    assert "not a clinical score" in lowered or "not clinical" in lowered
