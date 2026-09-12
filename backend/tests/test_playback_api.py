"""Program004 Slice B over HTTP - plan v2, playback commands, the event journal.

These are the properties a flaky mobile connection actually exercises: retries,
reordering, a second `complete` after the response was lost, and a process that
died and came back wanting to know where it was.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

CHECK_IN = {
    "goal": "overthinking",
    "stress": 8,
    "energy": 5,
    "mental_activity": 9,
    "sleepiness": 2,
    "available_minutes": 10,
    "experience_level": "beginner",
}


def start_session(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    created = client.post("/v1/check-ins", json=CHECK_IN, headers=headers)
    assert created.status_code == 201, created.text
    response = client.post(
        "/v1/sessions", json={"check_in_id": created.json()["id"]}, headers=headers
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def command(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    name: str,
    sequence: int,
    **extra: object,
) -> tuple[int, dict[str, object]]:
    payload = {
        "command": name,
        "command_id": f"{name}-{sequence}",
        "sequence": sequence,
        **extra,
    }
    response = client.post(f"/v1/sessions/{session_id}/playback", json=payload, headers=headers)
    return response.status_code, response.json()


def play_to(
    client: TestClient, headers: dict[str, str], session_id: str, *, through: str = "start"
) -> int:
    """Drive the run forward through the common prefix. Returns the next sequence."""
    steps = ["prepare", "resolved", "start"]
    sequence = 0
    for step in steps:
        sequence += 1
        status_code, body = command(client, headers, session_id, step, sequence)
        assert status_code == 200, body
        if step == through:
            break
    return sequence + 1


# --------------------------------------------------------------------------- #
# Plan v2 on the session
# --------------------------------------------------------------------------- #


def test_creating_a_session_returns_a_typed_plan(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    body = start_session(client, guest_headers)
    plan = body["plan_v2"]
    assert isinstance(plan, dict)
    assert len(str(plan["plan_hash"])) == 64
    assert len(str(plan["definition_id"])) == 64
    assert plan["practice_id"] == "body_awareness"
    assert plan["locale"] == "en-US"
    assert plan["target_total_ms"] == 604_000
    assert plan["minimum_total_ms"] <= plan["target_total_ms"]
    assert body["run_state"] == "created"
    # The Program001 plan is still there: this is an addition, not a swap.
    assert body["plan"]["protocol_id"]


def test_the_same_intent_produces_the_same_plan_hash_over_http(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    first = start_session(client, guest_headers)
    second = start_session(client, guest_headers)
    assert first["plan_v2"]["plan_hash"] == second["plan_v2"]["plan_hash"]
    assert first["plan_v2"]["definition_id"] == second["plan_v2"]["definition_id"]
    assert first["id"] != second["id"]


def test_plan_segments_are_typed_and_ordered(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    plan = start_session(client, guest_headers)["plan_v2"]
    segments = plan["segments"]
    assert segments[0]["kind"] == "bell"
    assert segments[-1]["kind"] == "bell"
    kinds = {s["kind"] for s in segments}
    assert kinds == {"bell", "speech", "silence", "marker"}
    speech = [s for s in segments if s["kind"] == "speech"]
    assert all(s["transcript"].strip() for s in speech)
    assert all(len(s["render_key"]) == 64 for s in speech)


def test_the_plan_carries_no_guest_identity(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Render keys are content-addressed; a cache keyed by guest would leak."""
    body = start_session(client, guest_headers)
    assert guest_headers["X-Guest-Id"] not in str(body["plan_v2"])


# --------------------------------------------------------------------------- #
# Playback commands
# --------------------------------------------------------------------------- #


def test_the_happy_path_walks_the_state_machine(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    expected = [
        ("prepare", "preparing"),
        ("resolved", "ready"),
        ("start", "playing"),
        ("pause", "paused"),
        ("resume", "playing"),
        ("complete", "completed"),
    ]
    for sequence, (name, state) in enumerate(expected, start=1):
        status_code, body = command(
            client, guest_headers, session_id, name, sequence, elapsed_ms=sequence * 1000
        )
        assert status_code == 200, body
        assert body["applied"] is True
        assert body["run_state"] == state

    session = client.get(f"/v1/sessions/{session_id}", headers=guest_headers).json()
    assert session["run_state"] == "completed"
    # The Program001 status column tracked along without knowing about run states.
    assert session["status"] == "completed"


def test_a_replayed_command_changes_nothing(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """A client that retried after losing the response is behaving correctly."""
    session_id = str(start_session(client, guest_headers)["id"])
    play_to(client, guest_headers, session_id)

    first_code, first = command(client, guest_headers, session_id, "pause", 4, elapsed_ms=9000)
    assert first_code == 200
    assert first["applied"] is True

    second_code, second = command(client, guest_headers, session_id, "pause", 4, elapsed_ms=9000)
    assert second_code == 200
    assert second["applied"] is False
    assert second["run_state"] == first["run_state"] == "paused"
    assert second["command_sequence"] == first["command_sequence"] == 4


def test_an_out_of_order_command_is_dropped_not_applied(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Rapid taps arrive shuffled; the later one already won."""
    session_id = str(start_session(client, guest_headers)["id"])
    play_to(client, guest_headers, session_id)
    command(client, guest_headers, session_id, "pause", 9, elapsed_ms=9000)

    status_code, body = command(client, guest_headers, session_id, "resume", 5, elapsed_ms=5000)
    assert status_code == 200
    assert body["applied"] is False
    assert body["run_state"] == "paused"
    assert body["command_sequence"] == 9


def test_a_second_complete_is_not_an_error(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Punishing a correct retry is how duplicate completions get written."""
    session_id = str(start_session(client, guest_headers)["id"])
    sequence = play_to(client, guest_headers, session_id)
    status_code, _ = command(
        client, guest_headers, session_id, "complete", sequence, elapsed_ms=600_000
    )
    assert status_code == 200

    status_code, body = command(
        client, guest_headers, session_id, "complete", sequence + 1, elapsed_ms=600_000
    )
    assert status_code == 200
    assert body["applied"] is False
    assert body["run_state"] == "completed"

    events = client.get("/v1/me/export", headers=guest_headers).json()["playback_events"]
    assert [e["event_type"] for e in events].count("session_completed") == 1


def test_a_command_colliding_with_a_journal_entry_is_rejected_atomically(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Applying the state change while losing its journal entry is not an option.

    Commands and events share one per-session counter. If a command lands on a
    sequence the journal already holds, the whole request rolls back rather than
    leaving a run that cannot be reconstructed.
    """
    session_id = str(start_session(client, guest_headers)["id"])
    client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"sequence": 1, "event_type": "segment_started", "elapsed_ms": 0}]},
        headers=guest_headers,
    )

    status_code, body = command(client, guest_headers, session_id, "prepare", 1)
    assert status_code == 409
    assert body["error"]["code"] == "sequence_conflict"

    # Rolled back: the run state did not move either.
    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["run_state"] == "created"
    assert state["command_sequence"] == 0


def test_an_illegal_transition_is_a_conflict(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Starting a session that was never prepared is a client bug, not a retry."""
    session_id = str(start_session(client, guest_headers)["id"])
    status_code, body = command(client, guest_headers, session_id, "start", 1)
    assert status_code == 409
    assert body["error"]["code"] == "invalid_transition"


def test_elapsed_time_never_moves_backwards(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """A reconnecting client reporting a smaller value is reporting a stale reading."""
    session_id = str(start_session(client, guest_headers)["id"])
    sequence = play_to(client, guest_headers, session_id)
    command(client, guest_headers, session_id, "pause", sequence, elapsed_ms=120_000)
    _, body = command(client, guest_headers, session_id, "resume", sequence + 1, elapsed_ms=500)
    assert body["elapsed_ms"] == 120_000


def test_an_unknown_command_is_rejected_by_the_schema(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    response = client.post(
        f"/v1/sessions/{session_id}/playback",
        json={"command": "rewind", "command_id": "x", "sequence": 1},
        headers=guest_headers,
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Recovery
# --------------------------------------------------------------------------- #


def test_recovery_resumes_at_the_start_of_the_last_segment(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Repeating one sentence beats joining one halfway through."""
    session = start_session(client, guest_headers)
    session_id = str(session["id"])
    speech = [s for s in session["plan_v2"]["segments"] if s["kind"] == "speech"][2]
    sequence = play_to(client, guest_headers, session_id)
    command(
        client,
        guest_headers,
        session_id,
        "pause",
        sequence,
        elapsed_ms=200_000,
        segment_id=speech["id"],
    )

    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["run_state"] == "paused"
    assert state["last_segment_id"] == speech["id"]
    assert state["resume_segment_id"] == speech["id"]
    assert state["resume_offset_ms"] < state["elapsed_ms"]
    assert state["applied"] is False


def test_recovery_on_an_untouched_session_starts_at_the_beginning(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["resume_segment_id"] is None
    assert state["resume_offset_ms"] == 0
    assert state["elapsed_ms"] == 0


# --------------------------------------------------------------------------- #
# The event journal
# --------------------------------------------------------------------------- #


def test_events_are_appended_and_deduplicated_by_sequence(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    batch = {
        "events": [
            {"sequence": 100, "event_type": "segment_started", "elapsed_ms": 0},
            {"sequence": 101, "event_type": "segment_completed", "elapsed_ms": 2000},
        ]
    }
    first = client.post(f"/v1/sessions/{session_id}/events", json=batch, headers=guest_headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"accepted": 2, "duplicates": 0}

    # The retry a dropped connection produces.
    second = client.post(f"/v1/sessions/{session_id}/events", json=batch, headers=guest_headers)
    assert second.status_code == 200
    assert second.json() == {"accepted": 0, "duplicates": 2}


def test_the_journal_offers_no_way_to_rewrite_history(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Append-only: a log that can be edited is not evidence."""
    from app.persistence.repositories import SessionEventRepository

    assert not hasattr(SessionEventRepository, "update")
    assert not hasattr(SessionEventRepository, "delete")

    session_id = str(start_session(client, guest_headers)["id"])
    original = {"events": [{"sequence": 1, "event_type": "segment_started", "elapsed_ms": 0}]}
    client.post(f"/v1/sessions/{session_id}/events", json=original, headers=guest_headers)
    overwrite = {
        "events": [{"sequence": 1, "event_type": "playback_failed", "elapsed_ms": 999_999}]
    }
    response = client.post(
        f"/v1/sessions/{session_id}/events", json=overwrite, headers=guest_headers
    )
    assert response.json() == {"accepted": 0, "duplicates": 1}

    events = client.get("/v1/me/export", headers=guest_headers).json()["playback_events"]
    stored = [e for e in events if e["sequence"] == 1]
    assert len(stored) == 1
    assert stored[0]["event_type"] == "segment_started"
    assert stored[0]["elapsed_ms"] == 0


def test_the_api_and_the_database_agree_on_event_types() -> None:
    """Two lists that must match, checked rather than hoped for."""
    import typing

    from app.api.v1.schemas import SessionEventType
    from app.persistence.models import SESSION_EVENT_TYPES

    assert typing.get_args(SessionEventType) == SESSION_EVENT_TYPES


def test_every_command_maps_to_a_declared_event_type() -> None:
    """A command whose journal entry the database would reject is a 500 waiting."""
    import typing

    from app.api.v1.routes import _EVENT_FOR_COMMAND
    from app.api.v1.schemas import PlaybackCommandRequest
    from app.persistence.models import SESSION_EVENT_TYPES

    commands = set(typing.get_args(PlaybackCommandRequest.model_fields["command"].annotation))
    assert set(_EVENT_FOR_COMMAND) == commands
    assert set(_EVENT_FOR_COMMAND.values()) <= set(SESSION_EVENT_TYPES)


def test_the_event_set_matches_the_sdd() -> None:
    """Section 17.1 verbatim, plus exactly the two the corrections require."""
    from app.persistence.models import SESSION_EVENT_TYPES

    sdd = {
        "session_created",
        "session_prepared",
        "session_started",
        "segment_started",
        "segment_completed",
        "playback_paused",
        "playback_resumed",
        "playback_interrupted",
        "playback_focus_regained",
        "route_changed",
        "session_completed",
        "session_abandoned",
        "render_cache_hit",
        "render_cache_miss",
        "render_failure",
        "timeline_compressed",
        "timeline_drift_exceeded",
        "silent_mode_used",
    }
    assert sdd <= set(SESSION_EVENT_TYPES)
    assert set(SESSION_EVENT_TYPES) - sdd == {"timeline_extended", "playback_failed"}


def test_an_unknown_event_type_is_rejected(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    response = client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"sequence": 1, "event_type": "vibes", "elapsed_ms": 0}]},
        headers=guest_headers,
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Guest isolation - mandatory security coverage
# --------------------------------------------------------------------------- #


@pytest.fixture
def other_headers() -> dict[str, str]:
    return {"X-Guest-Id": str(uuid.uuid4())}


def test_guest_b_cannot_command_guest_a_session(
    client: TestClient, guest_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    status_code, body = command(client, other_headers, session_id, "prepare", 1)
    assert status_code == 404
    assert body["error"]["code"] == "session_not_found"


def test_guest_b_cannot_read_guest_a_playback_state(
    client: TestClient, guest_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    for path in (f"/v1/sessions/{session_id}", f"/v1/sessions/{session_id}/playback"):
        assert client.get(path, headers=other_headers).status_code == 404


def test_guest_b_cannot_append_to_guest_a_journal(
    client: TestClient, guest_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    response = client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"sequence": 1, "event_type": "playback_failed", "elapsed_ms": 0}]},
        headers=other_headers,
    )
    assert response.status_code == 404


def test_guest_a_export_contains_no_guest_b_events(
    client: TestClient, guest_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    a_id = str(start_session(client, guest_headers)["id"])
    b_id = str(start_session(client, other_headers)["id"])
    play_to(client, guest_headers, a_id)
    play_to(client, other_headers, b_id)

    export = client.get("/v1/me/export", headers=guest_headers).json()
    session_ids = {e["session_id"] for e in export["playback_events"]}
    assert session_ids == {a_id}
    assert b_id not in str(export)


def test_deleting_a_guest_deletes_its_playback_journal(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Append-only is about rewriting, not about erasure rights."""
    session_id = str(start_session(client, guest_headers)["id"])
    play_to(client, guest_headers, session_id)
    assert client.get("/v1/me/export", headers=guest_headers).json()["playback_events"]

    assert client.delete("/v1/me/data", headers=guest_headers).status_code == 204
    assert client.get("/v1/me/export", headers=guest_headers).status_code == 404
    assert client.get(f"/v1/sessions/{session_id}", headers=guest_headers).status_code == 404


def test_playback_requires_a_guest_identity(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    assert client.get(f"/v1/sessions/{session_id}/playback").status_code == 401


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def test_literal_session_paths_are_not_shadowed(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Regression: /v1/sessions/{session_id} must not swallow /v1/sessions/history.

    FastAPI matches in registration order, so adding a parameterised path under
    an existing literal one silently turns the literal into a 422. This failed
    eleven history and privacy tests the first time it was written.
    """
    start_session(client, guest_headers)
    response = client.get("/v1/sessions/history", headers=guest_headers)
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_a_session_id_that_is_not_a_uuid_is_a_422(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    response = client.get("/v1/sessions/not-a-uuid", headers=guest_headers)
    assert response.status_code == 422
