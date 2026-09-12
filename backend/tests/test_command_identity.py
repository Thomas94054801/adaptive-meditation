"""Program004R Slice D — command identity, enforced by the database.

R09 and the G6 investigation. The question these tests answer is whether two
requests that look alike are the same command, and the answer has to survive
concurrency rather than a preceding SELECT.
"""

from __future__ import annotations

import concurrent.futures
import uuid

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.persistence.database import Database
from app.settings import Settings
from tests.test_playback_api import start_session


def command(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    *,
    name: str,
    command_id: str,
    sequence: int,
    elapsed_ms: int = 0,
    segment_id: str | None = None,
):
    payload: dict[str, object] = {
        "command": name,
        "command_id": command_id,
        "sequence": sequence,
        "elapsed_ms": elapsed_ms,
    }
    if segment_id is not None:
        payload["segment_id"] = segment_id
    return client.post(f"/v1/sessions/{session_id}/playback", json=payload, headers=headers)


def prepare_to_playing(client: TestClient, headers: dict[str, str], session_id: str) -> None:
    for sequence, name in enumerate(["prepare", "resolved", "start"], start=1):
        response = command(
            client,
            headers,
            session_id,
            name=name,
            command_id=f"{name}-{sequence}",
            sequence=sequence,
        )
        assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# R09: the same id, and the same id with different content
# --------------------------------------------------------------------------- #


def test_the_same_command_retried_returns_the_same_result(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """A lost ACK. The client retries with the same id; nothing is re-applied."""
    session_id = str(start_session(client, guest_headers)["id"])
    first = command(client, guest_headers, session_id, name="prepare", command_id="c-1", sequence=1)
    second = command(
        client, guest_headers, session_id, name="prepare", command_id="c-1", sequence=1
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["applied"] is True
    assert second.json()["applied"] is False
    assert second.json()["run_state"] == first.json()["run_state"]


def test_the_same_id_under_a_new_sequence_is_still_a_retry(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Retrying must not require inventing a new id — that makes one command two."""
    session_id = str(start_session(client, guest_headers)["id"])
    command(client, guest_headers, session_id, name="prepare", command_id="c-1", sequence=1)
    again = command(client, guest_headers, session_id, name="prepare", command_id="c-1", sequence=9)
    assert again.status_code == 200
    assert again.json()["applied"] is False
    assert again.json()["command_sequence"] == 1


def test_R09_the_same_id_with_different_content_is_a_conflict(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Reusing an id for a different command is a defect, not a duplicate."""
    session_id = str(start_session(client, guest_headers)["id"])
    prepare_to_playing(client, guest_headers, session_id)

    first = command(
        client,
        guest_headers,
        session_id,
        name="pause",
        command_id="reused",
        sequence=4,
        elapsed_ms=1000,
    )
    assert first.json()["applied"] is True

    conflicting = command(
        client,
        guest_headers,
        session_id,
        name="abandon",
        command_id="reused",
        sequence=5,
        elapsed_ms=2000,
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "command_payload_conflict"

    # And the run is untouched: still paused, not abandoned.
    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["run_state"] == "paused"


def test_a_differing_position_is_also_a_conflict(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The digest covers position, so the same command at a different point
    in the session is not the same command."""
    session_id = str(start_session(client, guest_headers)["id"])
    prepare_to_playing(client, guest_headers, session_id)
    command(
        client,
        guest_headers,
        session_id,
        name="pause",
        command_id="p-1",
        sequence=4,
        elapsed_ms=1000,
    )
    response = command(
        client,
        guest_headers,
        session_id,
        name="pause",
        command_id="p-1",
        sequence=4,
        elapsed_ms=99000,
    )
    assert response.status_code == 409


def test_the_journal_holds_exactly_one_row_per_command(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    for _ in range(5):
        command(client, guest_headers, session_id, name="prepare", command_id="once", sequence=1)
    export = client.get("/v1/me/export", headers=guest_headers).json()
    rows = [
        e
        for e in export["playback_events"]
        if e["session_id"] == session_id and e["command_id"] == "once"
    ]
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Concurrency: the reason a SELECT is not enough
# --------------------------------------------------------------------------- #


def test_concurrent_retries_of_one_command_apply_once(
    client: TestClient, guest_headers: dict[str, str], settings: Settings
) -> None:
    """Two retries in flight at once.

    A select-then-insert lets both pass the check and then both insert. Only
    the unique constraint stops that, which is why it exists.
    """
    session_id = str(start_session(client, guest_headers)["id"])

    def send() -> int:
        return command(
            client,
            guest_headers,
            session_id,
            name="prepare",
            command_id="racy",
            sequence=1,
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: send(), range(4)))

    # Every caller gets an answer; none gets a 500.
    assert all(code in {200, 409} for code in codes), codes

    database = Database(settings)
    try:
        with database.session() as db:
            count = db.execute(
                sa.text(
                    "SELECT count(*) FROM session_events "
                    "WHERE session_id = :sid AND command_id = 'racy'"
                ),
                {"sid": session_id},
            ).scalar_one()
    finally:
        database.dispose()
    assert count == 1, f"the command was recorded {count} times"


def test_the_database_enforces_command_uniqueness_directly(
    client: TestClient, guest_headers: dict[str, str], settings: Settings
) -> None:
    """The constraint, not the application, is the guarantee."""
    session_id = str(start_session(client, guest_headers)["id"])
    command(client, guest_headers, session_id, name="prepare", command_id="dup", sequence=1)

    database = Database(settings)
    try:
        with database.session() as db:
            try:
                db.execute(
                    sa.text(
                        "INSERT INTO session_events "
                        "(id, session_id, sequence, event_type, elapsed_ms, command_id) "
                        "VALUES (:id, :sid, 500, 'segment_started', 0, 'dup')"
                    ),
                    {"id": str(uuid.uuid4()), "sid": session_id},
                )
                db.flush()
                raise AssertionError("the unique constraint did not fire")
            except sa.exc.IntegrityError as error:
                assert "uq_session_events_command" in str(error)
                db.rollback()
    finally:
        database.dispose()


# --------------------------------------------------------------------------- #
# G6: reproduce or refute
# --------------------------------------------------------------------------- #


def test_G6_an_older_response_never_lowers_the_servers_sequence(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The server-side half of the G6 hypothesis.

    G6 supposed that a late response carrying an older command_sequence could
    push the client's sequence backwards. On the server side the invariant is
    simpler and is asserted here: applying an older command never lowers the
    stored sequence. The client-side half is covered by the Dart
    reconciliation tests, where the hypothesis was reproducible.
    """
    session_id = str(start_session(client, guest_headers)["id"])
    prepare_to_playing(client, guest_headers, session_id)

    command(
        client,
        guest_headers,
        session_id,
        name="pause",
        command_id="high",
        sequence=10,
        elapsed_ms=60_000,
    )
    state_after_high = client.get(
        f"/v1/sessions/{session_id}/playback", headers=guest_headers
    ).json()
    assert state_after_high["command_sequence"] == 10

    # A stale command arrives late with a lower number.
    late = command(
        client,
        guest_headers,
        session_id,
        name="resume",
        command_id="stale",
        sequence=4,
        elapsed_ms=1000,
    )
    assert late.status_code == 200
    assert late.json()["applied"] is False

    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["command_sequence"] == 10, "the sequence must never go backwards"
    assert state["run_state"] == "paused"
    assert state["elapsed_ms"] == 60_000, "and elapsed must never go backwards"


def test_a_terminal_run_is_not_revived_by_a_late_command(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    prepare_to_playing(client, guest_headers, session_id)
    command(
        client,
        guest_headers,
        session_id,
        name="complete",
        command_id="done",
        sequence=4,
        elapsed_ms=604_000,
    )

    late = command(
        client,
        guest_headers,
        session_id,
        name="resume",
        command_id="zombie",
        sequence=5,
        elapsed_ms=1000,
    )
    assert late.json()["applied"] is False
    state = client.get(f"/v1/sessions/{session_id}/playback", headers=guest_headers).json()
    assert state["run_state"] == "completed"


def test_a_deleted_guest_command_does_not_recreate_anything(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """R14: an in-flight request landing after deletion must not resurrect."""
    session_id = str(start_session(client, guest_headers)["id"])
    prepare_to_playing(client, guest_headers, session_id)
    assert client.delete("/v1/me/data", headers=guest_headers).status_code == 204

    late = command(
        client,
        guest_headers,
        session_id,
        name="pause",
        command_id="after-deletion",
        sequence=4,
    )
    assert late.status_code == 404
    assert client.get("/v1/me/export", headers=guest_headers).status_code == 404
