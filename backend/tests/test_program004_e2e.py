"""Program004 end-to-end: the whole journey, and what happens when it breaks.

Each test walks the real HTTP surface from check-in to feedback rather than
asserting on an internal call, because the properties worth proving here are
about the system agreeing with itself across layers - the plan the client gets,
the journal the server keeps and the history it later reports.

The failure-injection half matters more than the happy path. A meditation app
that works when everything works is not the interesting case.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.test_playback_api import CHECK_IN, command, start_session


def full_journey(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    """Check-in through feedback, the way the app does it."""
    session = start_session(client, headers)
    session_id = str(session["id"])

    client.post(f"/v1/sessions/{session_id}/prepare", headers=headers)
    for sequence, name in enumerate(["prepare", "resolved", "start"], start=1):
        status_code, _ = command(client, headers, session_id, name, sequence)
        assert status_code == 200

    client.post(
        f"/v1/sessions/{session_id}/events",
        json={
            "events": [
                {"sequence": 100 + i, "event_type": "segment_started", "elapsed_ms": i * 1000}
                for i in range(10)
            ]
        },
        headers=headers,
    )
    status_code, _ = command(client, headers, session_id, "complete", 4, elapsed_ms=604_000)
    assert status_code == 200

    feedback = client.post(
        f"/v1/sessions/{session_id}/feedback",
        json={
            "before_score": 3,
            "after_score": 7,
            "helpfulness": 4,
            "completed": True,
            "stress_after": 4,
            "energy_after": 5,
            "mental_activity_after": 4,
            "sleepiness_after": 3,
            "completion_ratio": 1.0,
        },
        headers=headers,
    )
    assert feedback.status_code == 204, feedback.text
    return session


# --------------------------------------------------------------------------- #
# 1. The whole journey
# --------------------------------------------------------------------------- #


def test_check_in_to_feedback_with_a_typed_plan(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = full_journey(client, guest_headers)
    session_id = str(session["id"])

    state = client.get(f"/v1/sessions/{session_id}", headers=guest_headers).json()
    assert state["run_state"] == "completed"
    assert state["status"] == "completed"
    assert state["plan_v2"]["plan_hash"] == session["plan_v2"]["plan_hash"]

    history = client.get("/v1/sessions/history", headers=guest_headers).json()
    assert [item["id"] for item in history["items"]] == [session_id]


def test_the_deterministic_recommendation_still_holds_end_to_end(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Program001's golden case, through the Program004 path.

    goal=overthinking, mental_activity=9, stress=8 must still give
    body_awareness, and the typed plan must describe that practice.
    """
    session = start_session(client, guest_headers)
    assert session["recommendation"]["practice_id"] == "body_awareness"
    assert session["plan_v2"]["practice_id"] == "body_awareness"
    assert session["plan_v2"]["target_total_ms"] == 604_000


def test_the_same_intent_twice_produces_the_same_plan_hash(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Reproducibility, over HTTP, across two independent sessions."""
    first = start_session(client, guest_headers)
    second = start_session(client, guest_headers)
    assert first["plan_v2"]["plan_hash"] == second["plan_v2"]["plan_hash"]
    assert first["plan_v2"]["definition_id"] == second["plan_v2"]["definition_id"]


def test_a_completed_session_is_reconstructible_from_its_own_records(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The point of freezing content: the session can be read back in full."""
    session = full_journey(client, guest_headers)
    export = client.get("/v1/me/export", headers=guest_headers).json()

    stored = next(s for s in export["sessions"] if s["id"] == str(session["id"]))
    assert stored["status"] == "completed"

    events = [e for e in export["playback_events"] if e["session_id"] == str(session["id"])]
    assert {e["event_type"] for e in events} >= {
        "session_created",
        "session_prepared",
        "session_started",
        "segment_started",
        "session_completed",
    }
    # The words are in the plan the session was created with, not in the journal.
    transcripts = [s["transcript"] for s in session["plan_v2"]["segments"] if s["kind"] == "speech"]
    assert all(text.strip() for text in transcripts)
    assert not any(text in str(events) for text in transcripts)


def test_two_guests_never_see_each_other(client: TestClient, guest_headers: dict[str, str]) -> None:
    """The mandatory isolation test, extended across every Program004 surface."""
    other = {"X-Guest-Id": str(uuid.uuid4())}
    mine = full_journey(client, guest_headers)
    theirs = full_journey(client, other)

    export = client.get("/v1/me/export", headers=guest_headers).json()
    assert str(theirs["id"]) not in str(export)
    assert {e["session_id"] for e in export["playback_events"]} == {str(mine["id"])}

    for path in (
        f"/v1/sessions/{theirs['id']}",
        f"/v1/sessions/{theirs['id']}/playback",
    ):
        assert client.get(path, headers=guest_headers).status_code == 404
    assert (
        client.post(f"/v1/sessions/{theirs['id']}/prepare", headers=guest_headers).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# 2. Failure injection
# --------------------------------------------------------------------------- #


def test_a_session_survives_the_client_dying_mid_playback(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Process death: the journal holds the last confirmed boundary."""
    session = start_session(client, guest_headers)
    session_id = str(session["id"])
    speech = [s for s in session["plan_v2"]["segments"] if s["kind"] == "speech"][1]

    for sequence, name in enumerate(["prepare", "resolved", "start"], start=1):
        command(client, guest_headers, session_id, name, sequence)
    command(
        client,
        guest_headers,
        session_id,
        "pause",
        4,
        elapsed_ms=180_000,
        segment_id=speech["id"],
    )

    # A fresh process asks where it was.
    recovered = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert recovered["run_state"] == "paused"
    assert recovered["resume_segment_id"] == speech["id"]
    assert recovered["resume_offset_ms"] < recovered["elapsed_ms"]

    # And resumes from there.
    status_code, body = command(client, guest_headers, session_id, "resume", 5, elapsed_ms=180_000)
    assert status_code == 200
    assert body["run_state"] == "playing"


def test_every_command_retried_once_changes_nothing(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """A flaky connection retrying each command must not double-apply any."""
    session_id = str(start_session(client, guest_headers)["id"])

    applied = 0
    for sequence, name in enumerate(["prepare", "resolved", "start", "complete"], start=1):
        payload = {
            "command": name,
            "command_id": f"once-{name}",
            "sequence": sequence,
            "elapsed_ms": sequence * 1000,
        }
        first = client.post(
            f"/v1/sessions/{session_id}/playback", json=payload, headers=guest_headers
        )
        second = client.post(
            f"/v1/sessions/{session_id}/playback", json=payload, headers=guest_headers
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200
        assert first.json()["applied"] is True
        assert second.json()["applied"] is False
        applied += 1

    export = client.get("/v1/me/export", headers=guest_headers).json()
    events = [e for e in export["playback_events"] if e["session_id"] == session_id]
    assert len(events) == applied


def test_a_duplicated_event_batch_does_not_duplicate_the_journal(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    batch = {
        "events": [
            {"sequence": n, "event_type": "segment_started", "elapsed_ms": n * 1000}
            for n in range(30)
        ]
    }
    for _ in range(3):
        client.post(f"/v1/sessions/{session_id}/events", json=batch, headers=guest_headers)

    export = client.get("/v1/me/export", headers=guest_headers).json()
    events = [e for e in export["playback_events"] if e["session_id"] == session_id]
    assert len(events) == 30
    assert len({e["sequence"] for e in events}) == 30


def test_commands_arriving_shuffled_leave_a_coherent_run(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Rapid taps on a bad connection. The later command wins; earlier ones drop."""
    session_id = str(start_session(client, guest_headers)["id"])
    for sequence, name in enumerate(["prepare", "resolved", "start"], start=1):
        command(client, guest_headers, session_id, name, sequence)

    command(client, guest_headers, session_id, "pause", 10, elapsed_ms=60_000)
    for stale in (4, 5, 9):
        _, body = command(client, guest_headers, session_id, "resume", stale, elapsed_ms=1000)
        assert body["applied"] is False

    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["run_state"] == "paused"
    assert state["command_sequence"] == 10
    assert state["elapsed_ms"] == 60_000


def test_an_illegal_transition_leaves_the_run_untouched(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    before = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()

    assert command(client, guest_headers, session_id, "resume", 1)[0] == 409

    after = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert after["run_state"] == before["run_state"]
    assert after["command_sequence"] == before["command_sequence"]


def test_a_failed_render_is_recoverable_rather_than_a_lost_session(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Nothing a user is likely to meet is fatal."""
    session_id = str(start_session(client, guest_headers)["id"])
    command(client, guest_headers, session_id, "prepare", 1)

    _, body = command(client, guest_headers, session_id, "unresolvable", 2)
    assert body["run_state"] == "failed"

    _, recovered = command(client, guest_headers, session_id, "recover", 3)
    assert recovered["run_state"] == "ready"
    _, playing = command(client, guest_headers, session_id, "start", 4)
    assert playing["run_state"] == "playing"


def test_deleting_a_guest_mid_session_removes_everything(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Deletion during a live run, which is the awkward moment for it."""
    session_id = str(start_session(client, guest_headers)["id"])
    for sequence, name in enumerate(["prepare", "resolved", "start"], start=1):
        command(client, guest_headers, session_id, name, sequence)

    assert client.delete("/v1/me/data", headers=guest_headers).status_code == 204

    assert client.get(f"/v1/sessions/{session_id}", headers=guest_headers).status_code == 404
    assert client.get("/v1/me/export", headers=guest_headers).status_code == 404
    # And a command on the vanished session is a 404, not a 500.
    assert command(client, guest_headers, session_id, "pause", 4)[0] == 404


def test_the_service_starts_and_recommends_with_no_ai_key(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The standing constraint, re-proved on the Program004 path."""
    health = client.get("/healthz").json()
    assert health["ai_provider_configured"] is False
    session = start_session(client, guest_headers)
    assert session["plan_v2"]["segments"]


@pytest.mark.parametrize("minutes", [3, 5, 10, 15, 20])
def test_every_offered_duration_produces_a_playable_plan(
    client: TestClient, guest_headers: dict[str, str], minutes: int
) -> None:
    """A duration that cannot be planned is one a user can still pick."""
    created = client.post(
        "/v1/check-ins", json={**CHECK_IN, "available_minutes": minutes}, headers=guest_headers
    )
    session = client.post(
        "/v1/sessions", json={"check_in_id": created.json()["id"]}, headers=guest_headers
    ).json()

    plan = session["plan_v2"]
    assert plan["segments"]
    assert any(s["kind"] == "speech" for s in plan["segments"])
    assert plan["minimum_total_ms"] <= plan["target_total_ms"]
