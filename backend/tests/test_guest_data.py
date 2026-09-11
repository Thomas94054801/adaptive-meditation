"""Guest-owned data: history, export and deletion."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.persistence import models

CHECK_IN = {
    "goal": "focus",
    "stress": 4,
    "energy": 9,
    "mental_activity": 5,
    "sleepiness": 2,
    "available_minutes": 10,
    "experience_level": "beginner",
}
FEEDBACK = {
    "after_score": 3,
    "helpfulness": 5,
    "completed": True,
    "before_score": 4,
    "stress_after": 2,
    "energy_after": 7,
    "mental_activity_after": 3,
    "sleepiness_after": 2,
    "completion_ratio": 1.0,
}


def run_session(client: TestClient, headers: dict[str, str], *, with_feedback: bool = True) -> str:
    receipt = client.post("/v1/check-ins", json=CHECK_IN, headers=headers)
    assert receipt.status_code == 201, receipt.text
    session = client.post(
        "/v1/sessions", json={"check_in_id": receipt.json()["id"]}, headers=headers
    )
    assert session.status_code == 201, session.text
    session_id = str(session.json()["id"])
    assert client.post(f"/v1/sessions/{session_id}/start", headers=headers).status_code == 204
    if with_feedback:
        assert (
            client.post(
                f"/v1/sessions/{session_id}/feedback", json=FEEDBACK, headers=headers
            ).status_code
            == 204
        )
    return session_id


# --- identity -----------------------------------------------------------------


def test_a_session_works_with_no_guest_identity_at_all(client: TestClient) -> None:
    """Guest-first means the header is optional, not merely unauthenticated."""
    receipt = client.post("/v1/check-ins", json=CHECK_IN)
    assert receipt.status_code == 201
    session = client.post("/v1/sessions", json={"check_in_id": receipt.json()["id"]})
    assert session.status_code == 201


def test_a_malformed_guest_header_is_rejected_not_ignored(client: TestClient) -> None:
    """Ignoring it would strand the data under an id nobody holds."""
    response = client.post("/v1/check-ins", json=CHECK_IN, headers={"X-Guest-Id": "nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_guest_id"


def test_history_requires_an_identity(client: TestClient) -> None:
    response = client.get("/v1/sessions/history")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "guest_id_required"


# --- history ------------------------------------------------------------------


def test_history_is_persisted_across_requests(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = run_session(client, guest_headers)
    body = client.get("/v1/sessions/history", headers=guest_headers).json()
    assert [item["id"] for item in body["items"]] == [session_id]
    assert body["items"][0]["practice_id"] == "mindful_walking"
    assert body["items"][0]["public_title"] == "Mindful Walk"
    assert body["items"][0]["rule_set_version"] == "2"
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_history_is_scoped_to_the_calling_guest(client: TestClient) -> None:
    first = {"X-Guest-Id": str(uuid.uuid4())}
    second = {"X-Guest-Id": str(uuid.uuid4())}
    run_session(client, first)
    assert client.get("/v1/sessions/history", headers=second).json()["items"] == []


def test_history_paginates_newest_first(client: TestClient, guest_headers: dict[str, str]) -> None:
    created = [run_session(client, guest_headers, with_feedback=False) for _ in range(5)]

    page = client.get("/v1/sessions/history?limit=2", headers=guest_headers).json()
    assert len(page["items"]) == 2
    assert page["has_more"] is True
    assert page["next_cursor"]

    seen = [item["id"] for item in page["items"]]
    cursor = page["next_cursor"]
    while cursor:
        page = client.get(
            f"/v1/sessions/history?limit=2&cursor={cursor}", headers=guest_headers
        ).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]

    assert seen == list(reversed(created))
    assert len(seen) == len(set(seen)), "pagination returned a duplicate"


def test_an_invalid_cursor_is_a_422(client: TestClient, guest_headers: dict[str, str]) -> None:
    response = client.get("/v1/sessions/history?cursor=!!!", headers=guest_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_history_limit_is_bounded(client: TestClient, guest_headers: dict[str, str]) -> None:
    assert client.get("/v1/sessions/history?limit=0", headers=guest_headers).status_code == 422
    assert client.get("/v1/sessions/history?limit=1000", headers=guest_headers).status_code == 422


# --- export -------------------------------------------------------------------


def test_export_contains_every_category(client: TestClient, guest_headers: dict[str, str]) -> None:
    run_session(client, guest_headers)
    body = client.get("/v1/me/export", headers=guest_headers).json()
    assert len(body["check_ins"]) == 1
    assert len(body["recommendations"]) == 1
    assert len(body["sessions"]) == 1
    assert len(body["feedback"]) == 1
    assert body["check_ins"][0]["goal"] == "focus"
    assert body["recommendations"][0]["practice_id"] == "mindful_walking"
    assert body["sessions"][0]["plan"]["stages"]
    assert body["feedback"][0]["stress_after"] == 2
    assert body["feedback"][0]["primary_measure"] == "activation"


def test_export_for_an_unknown_guest_is_404(client: TestClient) -> None:
    response = client.get("/v1/me/export", headers={"X-Guest-Id": str(uuid.uuid4())})
    assert response.status_code == 404


# --- deletion -----------------------------------------------------------------


def test_delete_removes_every_row_for_that_guest(
    client: TestClient, guest_headers: dict[str, str], settings: object
) -> None:
    """Counted per table, scoped to this guest.

    Scoped rather than global: other tests share the database, and a global
    count would make this pass or fail depending on execution order.
    """
    from app.persistence.database import Database

    run_session(client, guest_headers)
    guest_id = uuid.UUID(guest_headers["X-Guest-Id"])

    database = Database(settings)  # type: ignore[arg-type]

    def counts() -> dict[str, int]:
        with database.session() as session:
            session_ids = sa.select(models.Session.id).where(models.Session.guest_id == guest_id)
            return {
                "guest_profiles": session.execute(
                    sa.select(sa.func.count())
                    .select_from(models.GuestProfile)
                    .where(models.GuestProfile.id == guest_id)
                ).scalar_one(),
                "check_ins": session.execute(
                    sa.select(sa.func.count())
                    .select_from(models.CheckIn)
                    .where(models.CheckIn.guest_id == guest_id)
                ).scalar_one(),
                "sessions": session.execute(
                    sa.select(sa.func.count())
                    .select_from(models.Session)
                    .where(models.Session.guest_id == guest_id)
                ).scalar_one(),
                "session_feedback": session.execute(
                    sa.select(sa.func.count())
                    .select_from(models.SessionFeedback)
                    .where(models.SessionFeedback.session_id.in_(session_ids))
                ).scalar_one(),
                "recommendation_candidates": session.execute(
                    sa.select(sa.func.count())
                    .select_from(models.RecommendationCandidate)
                    .where(models.RecommendationCandidate.session_id.in_(session_ids))
                ).scalar_one(),
            }

    before = counts()
    assert all(value > 0 for value in before.values()), before
    # The candidate ranking really was persisted, not just the winner.
    assert before["recommendation_candidates"] >= 2

    assert client.delete("/v1/me/data", headers=guest_headers).status_code == 204

    after = counts()
    assert all(value == 0 for value in after.values()), after
    database.dispose()

    # And the guest is genuinely gone, not merely hidden.
    assert client.get("/v1/me/export", headers=guest_headers).status_code == 404
    assert client.get("/v1/sessions/history", headers=guest_headers).json()["items"] == []


def test_delete_does_not_touch_another_guest(client: TestClient) -> None:
    keep = {"X-Guest-Id": str(uuid.uuid4())}
    drop = {"X-Guest-Id": str(uuid.uuid4())}
    run_session(client, keep)
    run_session(client, drop)

    assert client.delete("/v1/me/data", headers=drop).status_code == 204
    assert len(client.get("/v1/sessions/history", headers=keep).json()["items"]) == 1


def test_delete_for_an_unknown_guest_is_404(client: TestClient) -> None:
    response = client.delete("/v1/me/data", headers={"X-Guest-Id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_delete_is_not_a_dark_pattern(client: TestClient, guest_headers: dict[str, str]) -> None:
    """One call, no confirmation token, no retention flag, no undo window."""
    run_session(client, guest_headers)
    response = client.delete("/v1/me/data", headers=guest_headers)
    assert response.status_code == 204
    assert response.content == b""
