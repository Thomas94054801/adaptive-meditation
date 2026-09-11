"""Deterministic session plan rendering tests."""

from __future__ import annotations

import pytest

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.session.planner import (
    ProtocolRenderError,
    allocate_stage_seconds,
    cue_interval_seconds,
    render_plan,
)
from app.domain.session.service import recommend_and_plan
from app.domain.state.models import AVAILABLE_MINUTES, CheckIn, ExperienceLevel, Goal


@pytest.mark.parametrize("minutes", AVAILABLE_MINUTES)
def test_plan_seconds_sum_exactly_to_the_duration(catalog: KnowledgeCatalog, minutes: int) -> None:
    for practice_id in catalog.practice_ids():
        protocol = catalog.protocol_for(practice_id)
        plan = render_plan(protocol, duration_minutes=minutes, guidance_density=0.5)
        assert sum(stage.duration_seconds for stage in plan.stages) == minutes * 60
        assert plan.total_seconds == minutes * 60


@pytest.mark.parametrize("minutes", AVAILABLE_MINUTES)
def test_stage_bounds_are_respected(catalog: KnowledgeCatalog, minutes: int) -> None:
    for practice_id in catalog.practice_ids():
        protocol = catalog.protocol_for(practice_id)
        plan = render_plan(protocol, duration_minutes=minutes, guidance_density=0.5)
        for declared, rendered in zip(protocol.stages, plan.stages, strict=True):
            assert declared.min_seconds <= rendered.duration_seconds <= declared.max_seconds
            assert rendered.silence_after_seconds <= rendered.duration_seconds // 3
            assert rendered.guidance_cue_count >= 1


def test_stage_offsets_are_contiguous(catalog: KnowledgeCatalog) -> None:
    plan = render_plan(
        catalog.protocol_for("body_awareness"), duration_minutes=15, guidance_density=0.65
    )
    offset = 0
    for stage in plan.stages:
        assert stage.start_offset_seconds == offset
        offset += stage.duration_seconds
    assert offset == plan.total_seconds


def test_rendering_is_deterministic(catalog: KnowledgeCatalog) -> None:
    protocol = catalog.protocol_for("breath_awareness")
    first = render_plan(protocol, duration_minutes=10, guidance_density=0.65).as_dict()
    for _ in range(50):
        assert render_plan(protocol, duration_minutes=10, guidance_density=0.65).as_dict() == first


def test_allocation_is_exact_for_every_renderable_second(catalog: KnowledgeCatalog) -> None:
    protocol = catalog.protocol_for("open_awareness")
    for total in range(protocol.min_total_seconds, protocol.max_total_seconds + 1):
        allocation = allocate_stage_seconds(protocol, total)
        assert sum(allocation) == total


def test_unsupported_duration_is_refused(catalog: KnowledgeCatalog) -> None:
    with pytest.raises(ProtocolRenderError, match="does not declare"):
        render_plan(
            catalog.protocol_for("breath_awareness"), duration_minutes=7, guidance_density=0.5
        )


def test_density_outside_the_protocol_range_is_refused(catalog: KnowledgeCatalog) -> None:
    with pytest.raises(ProtocolRenderError, match="outside protocol range"):
        render_plan(
            catalog.protocol_for("breath_awareness"), duration_minutes=10, guidance_density=0.95
        )


def test_denser_guidance_means_more_cues(catalog: KnowledgeCatalog) -> None:
    protocol = catalog.protocol_for("breath_awareness")
    sparse = render_plan(protocol, duration_minutes=20, guidance_density=0.30)
    dense = render_plan(protocol, duration_minutes=20, guidance_density=0.75)
    assert cue_interval_seconds(0.75) < cue_interval_seconds(0.30)
    assert sum(s.guidance_cue_count for s in dense.stages) > sum(
        s.guidance_cue_count for s in sparse.stages
    )


def test_prompt_placeholders_are_substituted(catalog: KnowledgeCatalog) -> None:
    plan = render_plan(
        catalog.protocol_for("body_awareness"), duration_minutes=15, guidance_density=0.5
    )
    joined = " ".join(stage.prompt for stage in plan.stages)
    assert "${" not in joined
    assert "15 minutes" in joined


def test_plan_title_uses_the_public_practice_name(catalog: KnowledgeCatalog) -> None:
    plan = render_plan(
        catalog.protocol_for("open_awareness"),
        duration_minutes=10,
        guidance_density=0.25,
        practice_public_title=catalog.practice("open_awareness").public_name,
    )
    assert plan.public_title == "Open Awareness"


def test_every_recommendation_renders(
    engine: RecommendationEngine, catalog: KnowledgeCatalog
) -> None:
    """The engine must never produce a recommendation the renderer cannot execute."""
    for goal in Goal:
        for level in ExperienceLevel:
            for minutes in AVAILABLE_MINUTES:
                for stress in (0, 5, 8, 10):
                    check_in = CheckIn.model_validate(
                        {
                            "goal": goal.value,
                            "stress": stress,
                            "energy": 5,
                            "mental_activity": 9,
                            "sleepiness": 8,
                            "available_minutes": minutes,
                            "experience_level": level.value,
                        }
                    )
                    recommendation, plan = recommend_and_plan(engine, check_in)
                    assert plan.practice_id == recommendation.practice_id
                    assert plan.total_seconds == recommendation.duration_minutes * 60
                    assert plan.guidance_density == recommendation.guidance_density
