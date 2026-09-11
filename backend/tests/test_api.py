"""API tests - SDD section 15.4, plus the full vertical slice end to end."""

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


def create_check_in(client: TestClient, payload: dict[str, object] | None = None) -> str:
    response = client.post("/v1/check-ins", json=payload or CHECK_IN)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def create_session(client: TestClient, check_in_id: str) -> dict[str, object]:
    response = client.post("/v1/sessions", json={"check_in_id": check_in_id})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_healthz_returns_200_without_an_ai_provider(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ai_provider_configured"] is False
    assert body["practices_loaded"] == body["protocols_loaded"] == 7
    # Read off the live engine, not a module constant that can go stale.
    assert body["engine_version"] == "2"
    assert body["rule_set_version"] == "2"
    assert body["knowledge_version"] == 2
    assert "rules_version" not in body


def test_recommendation_returns_200_and_schema_valid_json(client: TestClient) -> None:
    """Golden case A, over HTTP, with the v2 version triple."""
    response = client.post("/v1/recommendations", json=CHECK_IN)
    assert response.status_code == 200
    body = response.json()
    assert body["practice_id"] == "body_awareness"
    assert body["duration_minutes"] == 10
    assert body["guidance_density"] == 0.7
    assert body["reason_codes"] == [
        "goal_overthinking",
        "high_mental_activity",
        "high_stress",
    ]
    assert body["practice_public_name"] == "Body Awareness"
    assert body["engine_version"] == "2"
    assert body["rule_set_version"] == "2"
    assert body["protocol_version"] == "2"
    assert len(body["state_fingerprint"]) == 64
    # recommendation_version was replaced by the triple above and must be gone.
    assert "recommendation_version" not in body


def test_recommendation_candidates_expose_the_ranking(client: TestClient) -> None:
    response = client.post("/v1/recommendations/candidates", json=CHECK_IN)
    assert response.status_code == 200
    body = response.json()
    assert body["rule_set_version"] == "2"
    assert body["candidates"][0]["practice_id"] == "body_awareness"
    scores = [candidate["score"] for candidate in body["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 100 for score in scores)
    # A beginner cannot be offered open awareness.
    assert {e["practice_id"] for e in body["exclusions"]} == {"open_awareness"}


def test_the_normal_recommendation_response_has_no_candidate_list(
    client: TestClient,
) -> None:
    """Scores are an offline evaluation aid, not part of the client contract."""
    body = client.post("/v1/recommendations", json=CHECK_IN).json()
    assert "candidates" not in body
    assert "score" not in body


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(CHECK_IN | {"stress": -1}, id="stress_below_zero"),
        pytest.param(CHECK_IN | {"stress": 11}, id="stress_above_ten"),
        pytest.param(CHECK_IN | {"goal": "anxiety"}, id="unsupported_goal"),
        pytest.param(CHECK_IN | {"available_minutes": 7}, id="unsupported_duration"),
        pytest.param(CHECK_IN | {"experience_level": "expert"}, id="unsupported_experience"),
        pytest.param({"goal": "stress"}, id="missing_fields"),
    ],
)
def test_invalid_check_in_returns_422(client: TestClient, payload: dict[str, object]) -> None:
    for route in ("/v1/check-ins", "/v1/recommendations"):
        response = client.post(route, json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"


def test_check_in_is_persisted_and_echoed(client: TestClient) -> None:
    response = client.post("/v1/check-ins", json=CHECK_IN)
    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert body["check_in"] == CHECK_IN
    assert body["created_at"]


def test_session_can_be_created_from_a_valid_recommendation(client: TestClient) -> None:
    check_in_id = create_check_in(client)
    recommendation = client.post("/v1/recommendations", json=CHECK_IN).json()
    del recommendation["practice_public_name"]

    response = client.post(
        "/v1/sessions", json={"check_in_id": check_in_id, "recommendation": recommendation}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "created"
    assert body["recommendation"]["practice_id"] == "body_awareness"
    assert body["plan"]["practice_id"] == "body_awareness"
    assert body["plan"]["total_seconds"] == 600
    assert sum(stage["duration_seconds"] for stage in body["plan"]["stages"]) == 600
    assert body["plan"]["stages"][0]["start_offset_seconds"] == 0


def test_session_can_be_created_without_submitting_a_recommendation(client: TestClient) -> None:
    body = create_session(client, create_check_in(client))
    assert body["recommendation"]["practice_id"] == "body_awareness"


def test_submitted_recommendation_that_disagrees_is_rejected(client: TestClient) -> None:
    """A client cannot substitute a different practice family."""
    check_in_id = create_check_in(client)
    response = client.post(
        "/v1/sessions",
        json={
            "check_in_id": check_in_id,
            "recommendation": {
                "practice_id": "open_awareness",
                "duration_minutes": 20,
                "guidance_density": 0.2,
                "reason_codes": ["goal_overthinking"],
                "engine_version": "2",
                "rule_set_version": "2",
                "protocol_version": "2",
                "state_fingerprint": "0" * 64,
            },
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "recommendation_mismatch"


def test_session_for_unknown_check_in_returns_404(client: TestClient) -> None:
    response = client.post("/v1/sessions", json={"check_in_id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "check_in_not_found"


def test_feedback_can_be_attached_to_an_existing_session(client: TestClient) -> None:
    session = create_session(client, create_check_in(client))
    response = client.post(
        f"/v1/sessions/{session['id']}/feedback",
        json={"after_score": 3, "helpfulness": 4, "completed": True, "before_score": 8},
    )
    assert response.status_code == 204
    assert response.content == b""


def test_feedback_for_unknown_session_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/v1/sessions/{uuid.uuid4()}/feedback",
        json={"after_score": 3, "helpfulness": 4, "completed": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"after_score": 11, "helpfulness": 4, "completed": True}, id="score_high"),
        pytest.param({"after_score": 3, "helpfulness": 0, "completed": True}, id="helpfulness_low"),
        pytest.param(
            {"after_score": 3, "helpfulness": 6, "completed": True}, id="helpfulness_high"
        ),
        pytest.param({"after_score": 3, "helpfulness": 4}, id="missing_completed"),
        pytest.param(
            {"after_score": 3, "helpfulness": 4, "completed": True, "notes": "x" * 1001},
            id="notes_too_long",
        ),
    ],
)
def test_invalid_feedback_returns_422(client: TestClient, payload: dict[str, object]) -> None:
    session = create_session(client, create_check_in(client))
    response = client.post(f"/v1/sessions/{session['id']}/feedback", json=payload)
    assert response.status_code == 422


def test_start_then_feedback_moves_the_session_through_its_states(client: TestClient) -> None:
    session = create_session(client, create_check_in(client))
    assert client.post(f"/v1/sessions/{session['id']}/start").status_code == 204
    assert (
        client.post(
            f"/v1/sessions/{session['id']}/feedback",
            json={"after_score": 4, "helpfulness": 5, "completed": True, "notes": "steadier"},
        ).status_code
        == 204
    )


def test_start_for_unknown_session_returns_404(client: TestClient) -> None:
    response = client.post(f"/v1/sessions/{uuid.uuid4()}/start")
    assert response.status_code == 404


def test_abandoned_session_is_recorded_as_such(client: TestClient) -> None:
    session = create_session(client, create_check_in(client))
    response = client.post(
        f"/v1/sessions/{session['id']}/feedback",
        json={"after_score": 6, "helpfulness": 2, "completed": False},
    )
    assert response.status_code == 204


def test_full_vertical_slice_for_every_goal(client: TestClient) -> None:
    """check-in -> recommendation -> session -> start -> feedback, all six goals."""
    for goal in ("stress", "overthinking", "focus", "sleep", "emotional_reset", "general"):
        payload = CHECK_IN | {"goal": goal}
        recommendation = client.post("/v1/recommendations", json=payload)
        assert recommendation.status_code == 200

        check_in_id = create_check_in(client, payload)
        session = create_session(client, check_in_id)
        assert session["plan"]["stages"]
        assert client.post(f"/v1/sessions/{session['id']}/start").status_code == 204
        assert (
            client.post(
                f"/v1/sessions/{session['id']}/feedback",
                json={"after_score": 4, "helpfulness": 4, "completed": True},
            ).status_code
            == 204
        )


def test_guest_flow_sends_no_identity(client: TestClient) -> None:
    """Nothing in the slice requires or returns an account identifier."""
    session = create_session(client, create_check_in(client))
    assert "user_id" not in session
    assert "email" not in str(session)


@pytest.mark.parametrize("route", ["/privacy", "/terms", "/support", "/delete-account"])
def test_policy_routes_are_served(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_terms_carry_no_medical_claim(client: TestClient) -> None:
    body = client.get("/terms").text.lower()
    assert "does not diagnose" in body
    assert "not a substitute" in body


def test_delete_account_page_describes_the_capability_that_exists(
    client: TestClient,
) -> None:
    """Program001 said the feature was missing; Program002 built it.

    The page must now point at the real thing rather than still apologising.
    """
    body = client.get("/delete-account").text.lower()
    assert "no accounts" in body
    assert "delete my meditation data" in body
    assert "permanently" in body
    # And it must not promise anything that is not implemented.
    assert "waiting period" not in body.replace("there is no waiting period", "")


def test_privacy_page_describes_the_guest_identifier(client: TestClient) -> None:
    body = client.get("/privacy").text.lower()
    assert "random identifier" in body
    assert "advertising id" in body
    assert "export" in body
