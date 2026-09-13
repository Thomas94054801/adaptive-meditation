"""Program004 Slice B - typed timeline, timing feasibility, frozen definitions.

The claims under test are the ones the SDD makes about reproducibility: the same
recommendation intent, definition version and planner version must produce the
same canonical plan and the same plan_hash, and a session recorded last March
must stay interpretable after the knowledge files move on.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.playback.state_machine import (
    InvalidTransition,
    RunCommand,
    RunState,
    apply,
    is_terminal,
    reachable_states,
)
from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import Recommendation, RecommendationEngine
from app.domain.state.models import CheckIn, StateVector
from app.domain.timeline.definition import (
    SessionDefinition,
    definition_for,
    definition_from_protocol,
)
from app.domain.timeline.planner_v2 import (
    MIN_SPEECH_MS,
    PLANNER_VERSION,
    SessionPlanV2,
    build_plan,
    estimate_speech_ms,
    render_key_for,
)
from app.domain.timeline.segments import (
    BellId,
    BellSegment,
    SilenceSegment,
    SpeechSegment,
    Timeline,
    segment_as_dict,
    segment_from_dict,
)
from app.domain.timeline.service import plan_session, recovery_point
from app.domain.timeline.timing import SilenceAllocation, TimingOutcome, resolve_timing

CHECK_IN = {
    "goal": "overthinking",
    "stress": 8,
    "energy": 5,
    "mental_activity": 9,
    "sleepiness": 2,
    "available_minutes": 10,
    "experience_level": "beginner",
}


@pytest.fixture
def state() -> StateVector:
    return StateVector.from_check_in(CheckIn.model_validate(CHECK_IN))


@pytest.fixture
def recommendation(engine: RecommendationEngine, state: StateVector) -> Recommendation:
    return engine.recommend(state)


def plan_for(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> SessionPlanV2:
    definition = definition_for(catalog, recommendation.practice_id)
    protocol = catalog.protocol_for(recommendation.practice_id)
    return build_plan(recommendation, definition, protocol, state)


# --------------------------------------------------------------------------- #
# Segments
# --------------------------------------------------------------------------- #


def test_speech_segment_rejects_an_empty_transcript() -> None:
    """A speech segment with nothing to say is a silence segment with a bug."""
    with pytest.raises(ValueError, match="transcript"):
        SpeechSegment(id="s1", text="hello", transcript="  ", estimated_ms=1000, render_key="k")


def test_segments_round_trip_through_their_canonical_form() -> None:
    segments = (
        BellSegment(id="b1", bell_id=BellId.OPENING, duration_ms=2000, asset_key="bell.opening"),
        SpeechSegment(
            id="s1", text="Settle.", transcript="Settle.", estimated_ms=900, render_key="k"
        ),
        SilenceSegment(id="q1", target_ms=30_000, min_ms=12_000, elastic=True),
    )
    for segment in segments:
        assert segment_from_dict(segment_as_dict(segment)) == segment


def test_offsets_are_cumulative_and_start_at_zero() -> None:
    timeline = Timeline(
        segments=(
            BellSegment(
                id="b1", bell_id=BellId.OPENING, duration_ms=2000, asset_key="bell.opening"
            ),
            SilenceSegment(id="q1", target_ms=5000, min_ms=2000, elastic=True),
            BellSegment(
                id="b2", bell_id=BellId.CLOSING, duration_ms=2000, asset_key="bell.closing"
            ),
        )
    )
    assert timeline.offsets_ms() == (0, 2000, 7000)
    assert timeline.nominal_total_ms == 9000
    assert timeline.shrinkable_ms == 3000
    assert timeline.minimum_total_ms == 6000


# --------------------------------------------------------------------------- #
# Timing feasibility - the correction the SDD review demanded
# --------------------------------------------------------------------------- #


def _timeline() -> Timeline:
    """Bells 2s + 2s, speech estimated at 5s, one elastic silence 10s with a 4s floor.

    Nominal total 19s; shrinkable slack exactly 6s. Every boundary below is
    expressed against those numbers.
    """
    return Timeline(
        segments=(
            BellSegment(
                id="b1", bell_id=BellId.OPENING, duration_ms=2000, asset_key="bell.opening"
            ),
            SpeechSegment(id="s1", text="x", transcript="x", estimated_ms=5000, render_key="k"),
            SilenceSegment(id="q1", target_ms=10_000, min_ms=4000, elastic=True),
            BellSegment(
                id="b2", bell_id=BellId.CLOSING, duration_ms=2000, asset_key="bell.closing"
            ),
        )
    )


def test_speech_running_to_estimate_is_on_target() -> None:
    resolution = resolve_timing(_timeline(), {"s1": 5000})
    assert resolution.outcome is TimingOutcome.ON_TARGET
    assert resolution.extended_by_ms == 0
    assert resolution.actual_total_ms == resolution.target_total_ms == 19_000
    assert resolution.allocations[0].allocated_ms == 10_000


def test_speech_finishing_early_is_not_padded_out() -> None:
    """A shorter session is honest; stretching silence past its target is not."""
    resolution = resolve_timing(_timeline(), {"s1": 3000})
    assert resolution.outcome is TimingOutcome.ON_TARGET
    assert resolution.speech_overrun_ms == 0
    assert resolution.actual_total_ms == 17_000


def test_moderate_overrun_is_absorbed_by_elastic_silence() -> None:
    """Two seconds long: the silence gives up two seconds, duration holds."""
    resolution = resolve_timing(_timeline(), {"s1": 7000})
    assert resolution.outcome is TimingOutcome.ABSORBED
    assert resolution.speech_overrun_ms == 2000
    assert resolution.available_shrinkable_ms == 6000
    assert resolution.absorbed_ms == 2000
    assert resolution.extended_by_ms == 0
    assert resolution.actual_total_ms == 19_000
    assert resolution.allocations[0].allocated_ms == 8000


def test_overrun_of_exactly_the_budget_lands_on_the_floor() -> None:
    """The boundary case: every elastic millisecond spent, none borrowed."""
    resolution = resolve_timing(_timeline(), {"s1": 11_000})
    assert resolution.outcome is TimingOutcome.ABSORBED_AT_FLOOR
    assert resolution.absorbed_ms == resolution.available_shrinkable_ms == 6000
    assert resolution.extended_by_ms == 0
    assert resolution.actual_total_ms == 19_000
    allocation = resolution.allocations[0]
    assert allocation.allocated_ms == allocation.min_ms == 4000


def test_overrun_past_the_budget_extends_duration_and_says_so() -> None:
    """Never truncate guidance, never emit negative silence - extend and record."""
    resolution = resolve_timing(_timeline(), {"s1": 15_000})
    assert resolution.outcome is TimingOutcome.DURATION_EXTENDED
    assert resolution.was_extended
    assert resolution.absorbed_ms == 6000
    assert resolution.extended_by_ms == 4000
    assert resolution.actual_total_ms == 23_000
    assert resolution.allocations[0].allocated_ms == 4000


def test_no_measured_duration_at_all_resolves_to_the_plan() -> None:
    """Before anything is spoken, every segment is assumed to run to estimate."""
    resolution = resolve_timing(_timeline())
    assert resolution.outcome is TimingOutcome.ON_TARGET
    assert resolution.actual_total_ms == 19_000


def test_no_resolution_ever_produces_silence_below_its_floor() -> None:
    """The invariant, swept across the whole range including both boundaries."""
    for measured in (0, 1000, 5000, 10_999, 11_000, 11_001, 60_000, 600_000):
        resolution = resolve_timing(_timeline(), {"s1": measured})
        for allocation in resolution.allocations:
            assert allocation.allocated_ms >= allocation.min_ms >= 0
        assert resolution.extended_by_ms >= 0
        assert resolution.actual_total_ms >= resolution.allocations[0].min_ms


def test_a_negative_allocation_is_rejected_at_construction() -> None:
    """The type refuses to represent the thing the SDD review warned about."""
    with pytest.raises(ValueError, match="negative silence"):
        SilenceAllocation(segment_id="q1", target_ms=10_000, min_ms=0, allocated_ms=-1)
    with pytest.raises(ValueError, match="below the"):
        SilenceAllocation(segment_id="q1", target_ms=10_000, min_ms=4000, allocated_ms=3999)


def test_resolution_serialises_its_own_arithmetic() -> None:
    """Kept as evidence: a report can show why a session ran long."""
    payload = resolve_timing(_timeline(), {"s1": 15_000}).as_dict()
    assert payload["outcome"] == "duration_extended"
    assert payload["extended_by_ms"] == 4000
    assert payload["allocations"][0]["allocated_ms"] == 4000


# --------------------------------------------------------------------------- #
# Frozen definitions
# --------------------------------------------------------------------------- #


def test_definition_id_is_the_hash_of_its_own_content(catalog: KnowledgeCatalog) -> None:
    first = definition_for(catalog, "body_awareness")
    second = definition_for(catalog, "body_awareness")
    assert first.definition_id == second.definition_id
    assert len(first.definition_id) == 64


def test_changing_a_single_word_changes_the_definition_id(catalog: KnowledgeCatalog) -> None:
    """Content addressing is what makes "the same words" checkable."""
    original = definition_for(catalog, "body_awareness")
    first = original.stages[0]
    edited = dataclasses.replace(
        original,
        stages=(
            dataclasses.replace(first, prompt_template=first.prompt_template + " Gently."),
            *original.stages[1:],
        ),
    )
    assert edited.definition_id != original.definition_id


def test_a_stored_definition_stays_readable_after_the_catalog_moves_on(
    catalog: KnowledgeCatalog,
) -> None:
    """Historical reproducibility: the words live in the row, not in the files."""
    definition = definition_for(catalog, "body_awareness")
    restored = SessionDefinition.from_dict(definition.as_dict())
    assert restored == definition
    assert restored.definition_id == definition.definition_id


def test_definition_from_protocol_keeps_stage_order(catalog: KnowledgeCatalog) -> None:
    protocol = catalog.protocol_for("body_awareness")
    definition = definition_from_protocol(protocol, public_title="Body Awareness")
    assert [s.stage_id for s in definition.stages] == [s.id for s in protocol.stages]


def test_every_practice_freezes_into_a_definition(catalog: KnowledgeCatalog) -> None:
    """Reachability: a practice that cannot be frozen cannot be delivered."""
    for practice_id in catalog.practice_ids():
        definition = definition_for(catalog, practice_id)
        assert definition.stages
        assert all(stage.prompt_template.strip() for stage in definition.stages)
        assert all(stage.min_silence_seconds >= 0 for stage in definition.stages)


# --------------------------------------------------------------------------- #
# Planner v2
# --------------------------------------------------------------------------- #


def test_same_intent_produces_the_same_plan_hash(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    first = plan_for(catalog, recommendation, state)
    second = plan_for(catalog, recommendation, state)
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_plan_round_trips_without_changing_its_hash(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    plan = plan_for(catalog, recommendation, state)
    restored = SessionPlanV2.from_dict(plan.as_dict())
    assert restored.plan_hash == plan.plan_hash
    assert restored.transcript() == plan.transcript()


def test_plan_sums_to_the_recommended_duration_plus_its_bells(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    plan = plan_for(catalog, recommendation, state)
    assert plan.target_total_ms == recommendation.duration_minutes * 60_000 + 4000
    assert plan.planner_version == PLANNER_VERSION
    assert plan.definition_id == definition_for(catalog, recommendation.practice_id).definition_id


def test_silence_keeps_a_meaningful_floor(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    """A ten-minute session must not be able to collapse into two minutes of talk."""
    plan = plan_for(catalog, recommendation, state)
    assert plan.timeline.minimum_total_ms >= plan.target_total_ms * 0.4


def test_every_practice_plans_at_every_offered_duration(
    catalog: KnowledgeCatalog, engine: RecommendationEngine
) -> None:
    for practice_id in catalog.practice_ids():
        definition = definition_for(catalog, practice_id)
        protocol = catalog.protocol_for(practice_id)
        for minutes in (5, 10, 15, 20):
            state = StateVector.from_check_in(
                CheckIn.model_validate({**CHECK_IN, "available_minutes": minutes})
            )
            recommendation = engine.recommend(state).model_copy(
                update={"practice_id": practice_id, "protocol_id": protocol.id}
            )
            plan = build_plan(recommendation, definition, protocol, state)
            assert plan.timeline.speech()
            assert plan.timeline.minimum_total_ms <= plan.target_total_ms


def test_render_key_is_content_addressed_and_locale_aware() -> None:
    base = render_key_for("Breathe out.", "en-US", "voice-a", "calm", "fake", "1", "1")
    assert base == render_key_for("Breathe out.", "en-US", "voice-a", "calm", "fake", "1", "1")
    assert base != render_key_for("Breathe out.", "en-GB", "voice-a", "calm", "fake", "1", "1")
    assert base != render_key_for("Breathe in.", "en-US", "voice-a", "calm", "fake", "1", "1")
    assert base != render_key_for("Breathe out.", "en-US", "voice-b", "calm", "fake", "1", "1")
    assert base != render_key_for("Breathe out.", "en-US", "voice-a", "calm", "fake", "2", "1")


def test_render_key_carries_no_guest_identity() -> None:
    """Cache keys are content, never who asked - the cache is shared by design."""
    key = render_key_for("Settle.", "en-US", "voice-a", "calm", "fake", "1", "1")
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_speech_estimate_grows_with_the_text_above_its_floor() -> None:
    short = estimate_speech_ms("one two three")
    long = estimate_speech_ms(" ".join(["word"] * 200))
    assert short == MIN_SPEECH_MS  # too short to matter; the floor covers it
    assert long > short
    assert estimate_speech_ms("") == MIN_SPEECH_MS


# --------------------------------------------------------------------------- #
# Run state machine
# --------------------------------------------------------------------------- #


def test_interruption_never_auto_resumes() -> None:
    """A phone call ending is not consent to start meditating again."""
    assert apply(RunState.PLAYING, RunCommand.INTERRUPT).current is RunState.PAUSED
    assert apply(RunState.PAUSED, RunCommand.INTERRUPTION_ENDED).current is RunState.PAUSED


def test_terminal_states_accept_no_commands() -> None:
    for terminal in (RunState.COMPLETED, RunState.ABANDONED):
        assert is_terminal(terminal)
        for command in RunCommand:
            with pytest.raises(InvalidTransition):
                apply(terminal, command)


def test_failure_is_recoverable_rather_than_terminal() -> None:
    """A render that could not be resolved is a retry, not a lost session."""
    assert not is_terminal(RunState.FAILED)
    assert apply(RunState.FAILED, RunCommand.RECOVER).current is RunState.READY
    assert apply(RunState.FAILED, RunCommand.ABANDON).current is RunState.ABANDONED
    with pytest.raises(InvalidTransition):
        apply(RunState.FAILED, RunCommand.START)


def test_playing_requires_having_been_prepared() -> None:
    with pytest.raises(InvalidTransition):
        apply(RunState.CREATED, RunCommand.START)


def test_every_state_is_reachable_from_created() -> None:
    """An unreachable state is dead code that still has to be maintained."""
    assert reachable_states() == set(RunState)


def test_there_is_no_backgrounded_state() -> None:
    """Backgrounding is an OS event, not a run state."""
    assert "backgrounded" not in {s.value for s in RunState}


# --------------------------------------------------------------------------- #
# Service layer
# --------------------------------------------------------------------------- #


def test_plan_session_freezes_the_definition_it_planned_against(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    planned = plan_session(catalog, recommendation, state)
    assert planned.plan.definition_id == planned.definition.definition_id


def test_recovery_never_lands_mid_utterance(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    planned = plan_session(catalog, recommendation, state)
    speech = planned.plan.timeline.speech()[1]
    segment_id, offset_ms = recovery_point(planned.plan, speech.id)
    assert segment_id == speech.id
    index = planned.plan.timeline.segments.index(speech)
    assert offset_ms == planned.plan.timeline.offsets_ms()[index]


def test_recovery_from_an_unknown_segment_starts_over(
    catalog: KnowledgeCatalog, recommendation: Recommendation, state: StateVector
) -> None:
    """A plan that no longer holds that segment is a reason to restart, not to guess."""
    planned = plan_session(catalog, recommendation, state)
    assert recovery_point(planned.plan, "segment-from-another-plan") == (None, 0)
    assert recovery_point(planned.plan, None) == (None, 0)
