"""Exhaustive state-space verification.

One pass over all 1,317,690 reachable states, checking every invariant at once.
Separate from the sampled tests because it is the slow one, and combined into a
single pass because eleven passes over 1.3M states would cost eleven times as
much to learn the same thing.

Memory: states are generated lazily and never collected into a list. The only
things that accumulate are small counters and a set of practice ids - bounded by
the number of practices, not by the number of states.
"""

from __future__ import annotations

from collections import Counter

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.recommendation.rules_v2 import ALLOWED_REASON_CODES_V2
from app.domain.recommendation.versions import ENGINE_VERSION
from app.domain.session.planner import allocate_stage_seconds
from app.domain.state.models import ExperienceLevel, Goal

from .test_recommendation_engine import (
    EXPECTED_REACHABLE,
    FULL_STATE_SPACE_SIZE,
    iter_states,
)


def test_full_state_space_invariants(
    engine: RecommendationEngine, catalog: KnowledgeCatalog
) -> None:
    known = set(catalog.practice_ids())
    reached: set[str] = set()
    durations: Counter[int] = Counter()
    visited = 0

    for state in iter_states(sample=1):
        visited += 1
        result = engine.recommend_for_state(state)
        practice_id = result.practice_id

        # 1. the selected practice exists in the catalog
        assert practice_id in known
        practice = catalog.practice(practice_id)
        protocol = catalog.protocol_for(practice_id)

        # 2. reason codes stay inside the goal's declared vocabulary
        allowed = ALLOWED_REASON_CODES_V2[state.goal]
        assert result.reason_codes[0] == f"goal_{state.goal.value}"
        assert all(code in {c.value for c in allowed} for code in result.reason_codes)

        # 3. duration is supported and never exceeds what the user has
        assert protocol.supports_duration(result.duration_minutes)
        assert result.duration_minutes <= state.available_minutes

        # 4. guidance density is inside the protocol's declared range
        low, high = protocol.guidance_density_range
        assert low <= result.guidance_density <= high

        # 5. versions are stamped on every recommendation
        assert result.engine_version == ENGINE_VERSION
        assert result.rule_set_version == "2"
        assert result.state_fingerprint == state.fingerprint()

        # 6. no contraindication is violated
        assert not practice.is_contraindicated_for(state)

        # 7. no practice is offered below its minimum experience
        assert practice.meets_experience_floor(state.experience_level)

        reached.add(practice_id)
        durations[result.duration_minutes] += 1

    assert visited == FULL_STATE_SPACE_SIZE
    # 8. every intended practice is reachable
    assert reached == EXPECTED_REACHABLE
    assert set(durations) <= {3, 5, 10, 15, 20}


def test_every_recommendation_renders_an_exact_plan(
    engine: RecommendationEngine, catalog: KnowledgeCatalog
) -> None:
    """Stage seconds must sum to the session length for every reachable state.

    Adaptation weights differ per state, so this cannot be inferred from one
    render per protocol.
    """
    for state in iter_states(sample=3):
        result = engine.recommend_for_state(state)
        protocol = catalog.protocol_for(result.practice_id)
        total = result.duration_minutes * 60
        allocation = allocate_stage_seconds(protocol, total, state)
        assert sum(allocation) == total
        for stage, seconds in zip(protocol.stages, allocation, strict=True):
            assert stage.min_seconds <= seconds <= stage.max_seconds


def test_goal_and_experience_coverage_is_complete() -> None:
    """The enumeration really does cover every goal and experience level."""
    goals: set[Goal] = set()
    levels: set[ExperienceLevel] = set()
    for state in iter_states(sample=5):
        goals.add(state.goal)
        levels.add(state.experience_level)
    assert goals == set(Goal)
    assert levels == set(ExperienceLevel)
