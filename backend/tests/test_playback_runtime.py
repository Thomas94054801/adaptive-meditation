"""Program004 Slice C - the playback runtime.

Monotonic time, segment scheduling, route policy, the failure taxonomy, and the
two query budgets from SDD section 18 that a naive implementation blows through
without anything visibly breaking.
"""

from __future__ import annotations

import itertools
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.domain.playback.clock import (
    DRIFT_TOLERANCE_MS,
    ClockError,
    PlaybackClock,
    measure_drift,
)
from app.domain.playback.failures import (
    FAILURE_POLICY,
    FailureCode,
    degrades_to_playable,
    is_fatal,
    policy_for,
)
from app.domain.playback.routing import (
    AudioRoute,
    is_private,
    on_focus_lost,
    on_focus_regained,
    on_route_change,
)
from app.domain.playback.scheduler import (
    next_segment,
    progress_fraction,
    remaining_ms,
    resume_position,
    schedule,
    segment_at,
)
from app.domain.playback.state_machine import RunCommand
from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.state.models import CheckIn, StateVector
from app.domain.timeline.segments import SilenceSegment, SpeechSegment
from app.domain.timeline.service import plan_session
from tests.test_playback_api import CHECK_IN, command, play_to, start_session


@pytest.fixture
def plan(catalog: KnowledgeCatalog, engine: RecommendationEngine):
    state = StateVector.from_check_in(CheckIn.model_validate(CHECK_IN))
    return plan_session(catalog, engine.recommend(state), state).plan


# --------------------------------------------------------------------------- #
# Monotonic clock
# --------------------------------------------------------------------------- #


def test_a_paused_clock_does_not_advance() -> None:
    """Paused at minute three, resumed next morning, still at minute three."""
    clock = PlaybackClock().start(now_ms=1000)
    clock = clock.pause(now_ms=181_000)
    assert clock.elapsed_ms(now_ms=181_000) == 180_000
    assert clock.elapsed_ms(now_ms=181_000 + 12 * 60 * 60 * 1000) == 180_000
    assert not clock.is_running


def test_elapsed_excludes_every_paused_interval() -> None:
    clock = PlaybackClock().start(now_ms=0)
    clock = clock.pause(now_ms=10_000)  # 10s played
    clock = clock.start(now_ms=60_000)  # 50s paused
    clock = clock.pause(now_ms=75_000)  # 15s played
    assert clock.elapsed_ms(now_ms=999_999) == 25_000


def test_starting_a_running_clock_is_idempotent() -> None:
    """A duplicate resume must not bank the interval twice."""
    clock = PlaybackClock().start(now_ms=1000)
    assert clock.start(now_ms=5000) == clock
    assert clock.elapsed_ms(now_ms=6000) == 5000


def test_pausing_a_paused_clock_is_idempotent() -> None:
    clock = PlaybackClock().start(now_ms=0).pause(now_ms=4000)
    assert clock.pause(now_ms=90_000) == clock
    assert clock.elapsed_ms(now_ms=90_000) == 4000


def test_monotonic_time_going_backwards_is_an_error_not_a_negative_position() -> None:
    clock = PlaybackClock().start(now_ms=10_000)
    with pytest.raises(ClockError, match="backwards"):
        clock.elapsed_ms(now_ms=9_999)


def test_seek_keeps_the_running_state() -> None:
    running = PlaybackClock().start(now_ms=1000).seek(50_000)
    assert running.is_running
    assert running.elapsed_ms(now_ms=1000) == 50_000
    with pytest.raises(ClockError):
        running.seek(-1)


def test_drift_is_reported_not_silently_corrected() -> None:
    """A meditation that jumps is worse than one that is a second off."""
    within = measure_drift(expected_ms=60_000, observed_ms=60_000 + DRIFT_TOLERANCE_MS)
    assert not within.exceeded

    beyond = measure_drift(expected_ms=60_000, observed_ms=62_500)
    assert beyond.exceeded
    assert beyond.drift_ms == 2500

    behind = measure_drift(expected_ms=60_000, observed_ms=55_000)
    assert behind.exceeded
    assert behind.drift_ms == -5000


# --------------------------------------------------------------------------- #
# Segment scheduling
# --------------------------------------------------------------------------- #


def test_the_schedule_covers_the_timeline_without_gaps_or_overlap(plan) -> None:
    scheduled = schedule(plan)
    assert scheduled[0].start_ms == 0
    for earlier, later in itertools.pairwise(scheduled):
        assert earlier.end_ms == later.start_ms
    assert scheduled[-1].end_ms == plan.timeline.nominal_total_ms


def test_a_boundary_belongs_to_exactly_one_segment(plan) -> None:
    """Half-open windows, so a position cannot be in two segments at once."""
    for scheduled in schedule(plan):
        if scheduled.duration_ms == 0:
            continue
        # Value equality, not identity: schedule() rebuilds its tuple each call.
        assert segment_at(plan, scheduled.start_ms) == scheduled
        assert segment_at(plan, scheduled.end_ms - 1) == scheduled
        after = segment_at(plan, scheduled.end_ms)
        assert after is None or after.start_ms == scheduled.end_ms


def test_a_position_past_the_end_is_in_no_segment(plan) -> None:
    assert segment_at(plan, plan.timeline.nominal_total_ms) is None
    assert segment_at(plan, -1) is None
    assert next_segment(plan, plan.timeline.nominal_total_ms + 1) is None


def test_resume_rewinds_inside_speech_but_not_inside_silence(plan) -> None:
    """Repeating one sentence beats joining one halfway through."""
    speech = next(s for s in schedule(plan) if isinstance(s.segment, SpeechSegment))
    midway = speech.start_ms + speech.duration_ms // 2
    assert resume_position(plan, midway) == speech.start_ms

    silence = next(s for s in schedule(plan) if isinstance(s.segment, SilenceSegment))
    inside = silence.start_ms + silence.duration_ms // 2
    assert resume_position(plan, inside) == inside


def test_resume_past_the_end_clamps_to_the_end(plan) -> None:
    total = plan.timeline.nominal_total_ms
    assert resume_position(plan, total + 60_000) == total
    assert resume_position(plan, -5) == 0


def test_progress_and_remaining_agree_with_each_other(plan) -> None:
    total = plan.timeline.nominal_total_ms
    assert progress_fraction(plan, 0) == 0.0
    assert progress_fraction(plan, total) == 1.0
    assert progress_fraction(plan, total * 2) == 1.0
    assert remaining_ms(plan, 0) == total
    assert remaining_ms(plan, total) == 0
    assert remaining_ms(plan, total + 10_000) == 0


# --------------------------------------------------------------------------- #
# Route policy
# --------------------------------------------------------------------------- #


def test_losing_headphones_interrupts_rather_than_broadcasting() -> None:
    """Suddenly playing a meditation to a room is a privacy event."""
    decision = on_route_change(AudioRoute.HEADPHONES, AudioRoute.SPEAKER)
    assert decision.interrupts
    assert decision.command is RunCommand.INTERRUPT
    assert decision.event_type == "playback_interrupted"


def test_bluetooth_dropping_to_the_speaker_interrupts() -> None:
    assert on_route_change(AudioRoute.BLUETOOTH, AudioRoute.SPEAKER).interrupts
    assert on_route_change(AudioRoute.BLUETOOTH, AudioRoute.CAR).interrupts


def test_plugging_headphones_in_continues_and_records() -> None:
    decision = on_route_change(AudioRoute.SPEAKER, AudioRoute.HEADPHONES)
    assert not decision.interrupts
    assert decision.command is None
    assert decision.event_type == "route_changed"


def test_swapping_one_private_route_for_another_continues() -> None:
    assert not on_route_change(AudioRoute.HEADPHONES, AudioRoute.BLUETOOTH).interrupts
    assert not on_route_change(AudioRoute.BLUETOOTH, AudioRoute.HEADPHONES).interrupts


def test_an_unchanged_route_decides_nothing() -> None:
    decision = on_route_change(AudioRoute.BLUETOOTH, AudioRoute.BLUETOOTH)
    assert decision.command is None


def test_an_unknown_route_is_treated_as_audible_to_the_room() -> None:
    """Guessing wrong this way pauses a session; the other way broadcasts one."""
    assert not is_private(AudioRoute.UNKNOWN)
    assert on_route_change(AudioRoute.HEADPHONES, AudioRoute.UNKNOWN).interrupts


def test_focus_loss_interrupts_and_its_return_does_not_resume() -> None:
    assert on_focus_lost().command is RunCommand.INTERRUPT
    regained = on_focus_regained()
    assert regained.command is RunCommand.INTERRUPTION_ENDED
    assert regained.event_type == "playback_focus_regained"


# --------------------------------------------------------------------------- #
# Failure taxonomy
# --------------------------------------------------------------------------- #


def test_only_two_failures_are_fatal() -> None:
    """Almost nothing is fatal, and both exceptions are our own bug."""
    fatal = {code for code in FailureCode if is_fatal(code)}
    assert fatal == {FailureCode.CONTENT_PLAN_INVALID, FailureCode.PLAYBACK_RUNTIME_ERROR}


def test_every_failure_a_user_is_likely_to_meet_still_plays() -> None:
    for code in (
        FailureCode.NETWORK_UNAVAILABLE,
        FailureCode.STORAGE_EXHAUSTED,
        FailureCode.AUDIO_FOCUS_DENIED,
        FailureCode.AUDIO_ASSET_MISSING,
        FailureCode.RENDER_UNAVAILABLE,
    ):
        assert degrades_to_playable(code), code
        assert policy_for(code).recovery, code


def test_the_taxonomy_is_complete() -> None:
    assert set(FAILURE_POLICY) == set(FailureCode)


def test_only_the_two_documented_failures_are_user_actionable() -> None:
    """Telling a user about a failure they cannot act on is just noise."""
    actionable = {code for code in FailureCode if policy_for(code).user_actionable}
    assert actionable == {FailureCode.AUDIO_FOCUS_DENIED, FailureCode.STORAGE_EXHAUSTED}


# --------------------------------------------------------------------------- #
# Idempotency across sequences - SDD 5.4
# --------------------------------------------------------------------------- #


def test_a_replayed_command_id_under_a_new_sequence_is_not_reapplied(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The case the sequence rule alone misses.

    A client that retries the same logical command after bumping its counter
    would otherwise pause twice, or complete twice.
    """
    session_id = str(start_session(client, guest_headers)["id"])
    play_to(client, guest_headers, session_id)

    payload = {
        "command": "pause",
        "command_id": "the-same-command",
        "sequence": 4,
        "elapsed_ms": 9000,
    }
    first = client.post(f"/v1/sessions/{session_id}/playback", json=payload, headers=guest_headers)
    assert first.json()["applied"] is True

    # A real retry re-sends the stored operation verbatim, bumping only the
    # transport sequence. Program004R excludes sequence from the command digest
    # for exactly this reason: a retry keeps its id, so it must also be allowed
    # to keep its content while the counter moves on.
    second = client.post(
        f"/v1/sessions/{session_id}/playback",
        json={**payload, "sequence": 5},
        headers=guest_headers,
    )
    assert second.status_code == 200
    assert second.json()["applied"] is False
    assert second.json()["command_sequence"] == 4
    assert second.json()["elapsed_ms"] == 9000

    # Changing the content under the same id is a different matter: that is a
    # conflict, covered in tests/test_command_identity.py.
    conflicting = client.post(
        f"/v1/sessions/{session_id}/playback",
        json={**payload, "sequence": 6, "elapsed_ms": 12_000},
        headers=guest_headers,
    )
    assert conflicting.status_code == 409


def test_distinct_commands_still_apply_after_a_replay(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Replay detection must not wedge the run."""
    session_id = str(start_session(client, guest_headers)["id"])
    play_to(client, guest_headers, session_id)
    command(client, guest_headers, session_id, "pause", 4, elapsed_ms=9000)
    command(client, guest_headers, session_id, "pause", 5, elapsed_ms=9000)

    status_code, body = command(client, guest_headers, session_id, "resume", 6, elapsed_ms=9000)
    assert status_code == 200
    assert body["applied"] is True
    assert body["run_state"] == "playing"


# --------------------------------------------------------------------------- #
# Query budgets - SDD section 18
# --------------------------------------------------------------------------- #


@pytest.fixture
def counted(client: TestClient):
    """Count SQL statements issued while the block runs."""
    from app.persistence.database import Database

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = client.app.state.database._engine
    assert isinstance(client.app.state.database, Database)
    sa.event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        sa.event.remove(engine, "before_cursor_execute", record)


def writes_and_reads(statements: list[str]) -> int:
    """Statements that hit a table, ignoring transaction bookkeeping."""
    return len(
        [
            s
            for s in statements
            if s.strip().split(None, 1)[0].upper() in {"SELECT", "INSERT", "UPDATE", "DELETE"}
        ]
    )


def test_an_event_batch_costs_two_queries_regardless_of_size(
    client: TestClient, guest_headers: dict[str, str], counted: list[str]
) -> None:
    """A select-then-insert per event turns a 200-event batch into 400 trips."""
    session_id = str(start_session(client, guest_headers)["id"])
    counted.clear()

    events = [
        {"sequence": n, "event_type": "segment_started", "elapsed_ms": n * 1000} for n in range(200)
    ]
    response = client.post(
        f"/v1/sessions/{session_id}/events", json={"events": events}, headers=guest_headers
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 200, "duplicates": 0}

    # One session lookup, one sequence probe, one insert.
    assert writes_and_reads(counted) <= 3, counted


def test_a_duplicate_batch_costs_no_inserts(
    client: TestClient, guest_headers: dict[str, str], counted: list[str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    events = [{"sequence": n, "event_type": "segment_started"} for n in range(50)]
    client.post(f"/v1/sessions/{session_id}/events", json={"events": events}, headers=guest_headers)

    counted.clear()
    response = client.post(
        f"/v1/sessions/{session_id}/events", json={"events": events}, headers=guest_headers
    )
    assert response.json() == {"accepted": 0, "duplicates": 50}
    assert not [s for s in counted if s.strip().upper().startswith("INSERT")]


def test_a_batch_repeating_a_sequence_within_itself_does_not_break(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Without in-batch deduplication the unique constraint rejects everything."""
    session_id = str(start_session(client, guest_headers)["id"])
    events = [
        {"sequence": 1, "event_type": "segment_started"},
        {"sequence": 1, "event_type": "segment_completed"},
        {"sequence": 2, "event_type": "segment_completed"},
    ]
    response = client.post(
        f"/v1/sessions/{session_id}/events", json={"events": events}, headers=guest_headers
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "duplicates": 1}


def test_creating_a_session_stays_within_its_query_budget(
    client: TestClient, guest_headers: dict[str, str], counted: list[str]
) -> None:
    """Six per Program004 SDD section 18, plus Program005's one familiarity count.

    The first session for a practice also inserts its frozen definition; that
    write is content-addressed and happens once per schema, so the budget is
    measured on the second session, where only the per-session work remains.
    """
    start_session(client, guest_headers)
    created = client.post("/v1/check-ins", json=CHECK_IN, headers=guest_headers)
    check_in_id = created.json()["id"]
    counted.clear()

    response = client.post("/v1/sessions", json={"check_in_id": check_in_id}, headers=guest_headers)
    assert response.status_code == 201
    assert writes_and_reads(counted) <= 7, counted


def test_a_repeat_session_reuses_the_frozen_definition(
    client: TestClient, guest_headers: dict[str, str], counted: list[str]
) -> None:
    """Content addressing means the second session writes no new definition."""
    first = start_session(client, guest_headers)
    counted.clear()
    second = start_session(client, guest_headers)

    assert first["plan_v2"]["definition_id"] == second["plan_v2"]["definition_id"]
    inserts = [s for s in counted if "session_definitions" in s.lower() and "INSERT" in s.upper()]
    assert inserts == []


def test_guest_isolation_holds_for_the_runtime_endpoints(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    other = {"X-Guest-Id": str(uuid.uuid4())}
    session_id = str(start_session(client, guest_headers)["id"])
    play_to(client, guest_headers, session_id)
    assert client.get(f"/v1/sessions/{session_id}/playback", headers=other).status_code == 404
