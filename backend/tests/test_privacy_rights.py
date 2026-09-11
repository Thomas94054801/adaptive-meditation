"""Deletion and export as user rights - SDD_PROGRAM003 sections 20, 21, 45, 46.

Two properties, both security-relevant:

1. deletion actually deletes, everywhere, and the old identifier stops working;
2. an export can only ever return the caller's own data.

The export isolation test is mandatory. An export endpoint that could be made to
return someone else's data is the worst failure this service could have, and it
is the kind that passes every functional test.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.domain.experiment.assignment import EXPLANATION_COPY_EXPERIMENT
from app.persistence import models
from app.persistence.database import Database
from app.settings import Settings

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
    "notes": "steadier",
}


def full_journey(client: TestClient, headers: dict[str, str]) -> str:
    """Everything a guest can create: check-in, recommendation, session,
    feedback, candidates, experiment assignment and exposure."""
    recommendation = client.post("/v1/recommendations", json=CHECK_IN, headers=headers)
    assert recommendation.status_code == 200

    receipt = client.post("/v1/check-ins", json=CHECK_IN, headers=headers)
    assert receipt.status_code == 201
    session = client.post(
        "/v1/sessions", json={"check_in_id": receipt.json()["id"]}, headers=headers
    )
    assert session.status_code == 201
    session_id = str(session.json()["id"])

    assert client.post(f"/v1/sessions/{session_id}/start", headers=headers).status_code == 204
    assert (
        client.post(
            f"/v1/sessions/{session_id}/feedback", json=FEEDBACK, headers=headers
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/v1/experiments/exposures",
            json={"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": session_id},
            headers=headers,
        ).status_code
        == 200
    )
    return session_id


def row_counts(database: Database, guest_id: uuid.UUID) -> dict[str, int]:
    """Rows belonging to one guest, per table."""
    with database.session() as session:
        session_ids = sa.select(models.Session.id).where(models.Session.guest_id == guest_id)

        def count(model: type, where: sa.ColumnElement[bool]) -> int:
            return int(
                session.execute(
                    sa.select(sa.func.count()).select_from(model).where(where)
                ).scalar_one()
            )

        return {
            "guest_profiles": count(models.GuestProfile, models.GuestProfile.id == guest_id),
            "check_ins": count(models.CheckIn, models.CheckIn.guest_id == guest_id),
            "sessions": count(models.Session, models.Session.guest_id == guest_id),
            "session_feedback": count(
                models.SessionFeedback,
                models.SessionFeedback.session_id.in_(session_ids),
            ),
            "recommendation_candidates": count(
                models.RecommendationCandidate,
                models.RecommendationCandidate.session_id.in_(session_ids),
            ),
            "experiment_assignments": count(
                models.ExperimentAssignment,
                models.ExperimentAssignment.guest_id == guest_id,
            ),
            "experiment_exposures": count(
                models.ExperimentExposure, models.ExperimentExposure.guest_id == guest_id
            ),
        }


# --- deletion -----------------------------------------------------------------


def test_deletion_removes_every_associated_row(client: TestClient, settings: Settings) -> None:
    guest_id = uuid.uuid4()
    headers = {"X-Guest-Id": str(guest_id)}
    full_journey(client, headers)

    database = Database(settings)
    try:
        before = row_counts(database, guest_id)
        assert all(value > 0 for value in before.values()), before

        assert client.delete("/v1/me/data", headers=headers).status_code == 204

        after = row_counts(database, guest_id)
        assert all(value == 0 for value in after.values()), after
    finally:
        database.dispose()


def test_the_old_identifier_cannot_retrieve_the_deleted_history(
    client: TestClient,
) -> None:
    """The point of deletion, stated as the user would state it."""
    headers = {"X-Guest-Id": str(uuid.uuid4())}
    full_journey(client, headers)

    assert client.get("/v1/sessions/history", headers=headers).json()["items"]
    assert client.delete("/v1/me/data", headers=headers).status_code == 204

    assert client.get("/v1/sessions/history", headers=headers).json()["items"] == []
    assert client.get("/v1/me/export", headers=headers).status_code == 404
    assert client.delete("/v1/me/data", headers=headers).status_code == 404


def test_deletion_is_hard_not_soft(client: TestClient, settings: Settings) -> None:
    """No tombstone. The retention policy says the data is gone, so it must be.

    A soft delete would make the honest answer to "is it deleted" no, which is
    not what the deletion surface tells the user.
    """
    guest_id = uuid.uuid4()
    headers = {"X-Guest-Id": str(guest_id)}
    full_journey(client, headers)
    client.delete("/v1/me/data", headers=headers)

    database = Database(settings)
    try:
        with database.session() as session:
            assert session.get(models.GuestProfile, guest_id) is None
    finally:
        database.dispose()


def test_a_new_identity_after_deletion_starts_empty(client: TestClient) -> None:
    """The client rotates its identifier after deleting; the new one is clean."""
    old = {"X-Guest-Id": str(uuid.uuid4())}
    full_journey(client, old)
    client.delete("/v1/me/data", headers=old)

    new = {"X-Guest-Id": str(uuid.uuid4())}
    assert client.get("/v1/sessions/history", headers=new).json()["items"] == []


def test_deleting_one_guest_does_not_touch_another(client: TestClient, settings: Settings) -> None:
    keep_id, drop_id = uuid.uuid4(), uuid.uuid4()
    keep = {"X-Guest-Id": str(keep_id)}
    drop = {"X-Guest-Id": str(drop_id)}
    full_journey(client, keep)
    full_journey(client, drop)

    database = Database(settings)
    try:
        before = row_counts(database, keep_id)
        assert client.delete("/v1/me/data", headers=drop).status_code == 204
        assert row_counts(database, keep_id) == before
        assert all(value == 0 for value in row_counts(database, drop_id).values())
    finally:
        database.dispose()
    assert client.get("/v1/sessions/history", headers=keep).json()["items"]


# --- export isolation ---------------------------------------------------------


def test_export_returns_only_the_callers_own_data(client: TestClient) -> None:
    """Mandatory security test.

    Guest A and Guest B both have data. A's export must contain zero B records.
    """
    a_id, b_id = uuid.uuid4(), uuid.uuid4()
    a = {"X-Guest-Id": str(a_id)}
    b = {"X-Guest-Id": str(b_id)}

    a_session = full_journey(client, a)
    b_session = full_journey(client, b)
    assert a_session != b_session

    export = client.get("/v1/me/export", headers=a).json()
    assert export["guest_id"] == str(a_id)

    serialized = str(export)
    assert str(b_id) not in serialized, "another guest's id appeared in the export"
    assert b_session not in serialized, "another guest's session appeared in the export"

    session_ids = {row["id"] for row in export["sessions"]}
    assert session_ids == {a_session}
    assert len(export["check_ins"]) == 1
    assert len(export["feedback"]) == 1


def test_export_cannot_be_widened_by_a_forged_identifier(client: TestClient) -> None:
    """There is no parameter that names another guest, so there is nothing to forge.

    The endpoint takes its subject from the header and nothing else; this
    asserts that a caller cannot reach data by inventing an identifier.
    """
    victim = {"X-Guest-Id": str(uuid.uuid4())}
    full_journey(client, victim)

    attacker = {"X-Guest-Id": str(uuid.uuid4())}
    assert client.get("/v1/me/export", headers=attacker).status_code == 404
    assert client.get("/v1/sessions/history", headers=attacker).json()["items"] == []


def test_history_is_isolated_between_guests(client: TestClient) -> None:
    a = {"X-Guest-Id": str(uuid.uuid4())}
    b = {"X-Guest-Id": str(uuid.uuid4())}
    a_session = full_journey(client, a)
    b_session = full_journey(client, b)

    a_items = {row["id"] for row in client.get("/v1/sessions/history", headers=a).json()["items"]}
    b_items = {row["id"] for row in client.get("/v1/sessions/history", headers=b).json()["items"]}

    assert a_items == {a_session}
    assert b_items == {b_session}
    assert a_items.isdisjoint(b_items)


def test_export_is_complete(client: TestClient) -> None:
    """Every category the guest can create must appear."""
    headers = {"X-Guest-Id": str(uuid.uuid4())}
    full_journey(client, headers)
    export = client.get("/v1/me/export", headers=headers).json()

    for category in (
        "check_ins",
        "recommendations",
        "sessions",
        "feedback",
        "experiment_assignments",
        "experiment_exposures",
    ):
        assert export[category], f"{category} missing from the export"

    feedback = export["feedback"][0]
    assert feedback["stress_after"] == 2
    assert feedback["notes"] == "steadier"
    assert feedback["primary_measure"] == "activation"
