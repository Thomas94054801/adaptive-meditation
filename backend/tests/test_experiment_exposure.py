"""Experiment assignment, exposure, and the boundary between them.

SDD_PROGRAM003 sections 7 and 43. The distinction these tests defend is that
assignment is not exposure: counting the two as one would inflate every
denominator the experiment exists to measure.
"""

from __future__ import annotations

import uuid
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.domain.experiment.assignment import (
    EXPLANATION_COPY_EXPERIMENT,
    assign,
    get_experiment,
)
from app.domain.experiment.safety import (
    ALLOWED_EXPERIMENT_SURFACES,
    PROTECTED_FROM_EXPERIMENTS,
    ExperimentBoundaryError,
    assert_presentation_only,
)

CHECK_IN = {
    "goal": "overthinking",
    "stress": 8,
    "energy": 5,
    "mental_activity": 9,
    "sleepiness": 2,
    "available_minutes": 10,
    "experience_level": "beginner",
}


# --- determinism --------------------------------------------------------------


def test_the_same_guest_and_experiment_always_gets_the_same_variant() -> None:
    experiment = get_experiment(EXPLANATION_COPY_EXPERIMENT)
    guest = str(uuid.uuid4())
    first = assign(guest, experiment).variant
    for _ in range(500):
        assert assign(guest, experiment).variant == first


def test_different_guests_distribute_across_variants() -> None:
    experiment = get_experiment(EXPLANATION_COPY_EXPERIMENT)
    counts = Counter(assign(str(uuid.UUID(int=i)), experiment).variant for i in range(4000))
    assert set(counts) == set(experiment.variants)
    for value in counts.values():
        assert 1500 < value < 2500, counts


def test_the_api_returns_the_same_variant_the_domain_assigns(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    expected = assign(guest_headers["X-Guest-Id"], get_experiment(EXPLANATION_COPY_EXPERIMENT))
    body = client.post("/v1/recommendations", json=CHECK_IN, headers=guest_headers).json()
    assert body["explanation_variant"]["experiment_id"] == expected.experiment_id
    assert body["explanation_variant"]["variant"] == expected.variant


def test_a_caller_without_a_guest_identity_gets_no_variant(client: TestClient) -> None:
    """An assignment that cannot be recorded cannot be analysed either."""
    body = client.post("/v1/recommendations", json=CHECK_IN).json()
    assert body["explanation_variant"] is None


# --- assignment is not exposure -----------------------------------------------


def test_requesting_a_recommendation_assigns_but_does_not_expose(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    client.post("/v1/recommendations", json=CHECK_IN, headers=guest_headers)
    export = client.get("/v1/me/export", headers=guest_headers).json()
    assert len(export["experiment_assignments"]) == 1
    assert export["experiment_exposures"] == []


def test_exposure_is_recorded_only_when_reported(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    client.post("/v1/recommendations", json=CHECK_IN, headers=guest_headers)
    response = client.post(
        "/v1/experiments/exposures",
        json={"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": "check-in-1"},
        headers=guest_headers,
    )
    assert response.status_code == 200
    assert response.json()["recorded"] is True

    export = client.get("/v1/me/export", headers=guest_headers).json()
    assert len(export["experiment_exposures"]) == 1
    assert export["experiment_exposures"][0]["context"] == "check-in-1"


def test_exposure_is_logged_exactly_once_per_context(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    payload = {"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": "check-in-1"}
    first = client.post("/v1/experiments/exposures", json=payload, headers=guest_headers)
    repeats = [
        client.post("/v1/experiments/exposures", json=payload, headers=guest_headers)
        for _ in range(5)
    ]

    assert first.json()["recorded"] is True
    assert all(r.json()["recorded"] is False for r in repeats)
    export = client.get("/v1/me/export", headers=guest_headers).json()
    assert len(export["experiment_exposures"]) == 1


def test_a_different_context_is_a_different_exposure(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    for context in ("check-in-1", "check-in-2", "check-in-3"):
        client.post(
            "/v1/experiments/exposures",
            json={"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": context},
            headers=guest_headers,
        )
    export = client.get("/v1/me/export", headers=guest_headers).json()
    assert len(export["experiment_exposures"]) == 3


def test_the_exposed_variant_matches_the_assigned_one(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    assigned = client.post("/v1/recommendations", json=CHECK_IN, headers=guest_headers).json()[
        "explanation_variant"
    ]["variant"]
    exposed = client.post(
        "/v1/experiments/exposures",
        json={"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": "c1"},
        headers=guest_headers,
    ).json()["variant"]
    assert exposed == assigned


def test_exposure_requires_a_guest_identity(client: TestClient) -> None:
    response = client.post(
        "/v1/experiments/exposures",
        json={"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": "c1"},
    )
    assert response.status_code == 401


def test_an_unknown_experiment_is_refused(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/experiments/exposures",
        json={"experiment_id": "not_an_experiment", "context": "c1"},
        headers=guest_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_experiment"


# --- the safety boundary ------------------------------------------------------


def test_the_experiment_does_not_change_the_recommendation(
    client: TestClient,
) -> None:
    """The decision must be identical across variants.

    Runs enough distinct guests to cover both arms, and asserts the practice,
    duration and density never move.
    """
    seen_variants: set[str] = set()
    decisions: set[tuple[str, int, float]] = set()

    for index in range(60):
        headers = {"X-Guest-Id": str(uuid.UUID(int=index))}
        body = client.post("/v1/recommendations", json=CHECK_IN, headers=headers).json()
        seen_variants.add(body["explanation_variant"]["variant"])
        decisions.add((body["practice_id"], body["duration_minutes"], body["guidance_density"]))

    assert len(seen_variants) == 2, "both arms must be represented"
    assert decisions == {("body_awareness", 10, 0.7)}


@pytest.mark.parametrize("surface", sorted(PROTECTED_FROM_EXPERIMENTS))
def test_protected_surfaces_are_refused(surface: str) -> None:
    with pytest.raises(ExperimentBoundaryError):
        assert_presentation_only(surface)


@pytest.mark.parametrize("surface", sorted(ALLOWED_EXPERIMENT_SURFACES))
def test_presentation_surfaces_are_allowed(surface: str) -> None:
    assert_presentation_only(surface)


def test_an_undeclared_surface_is_refused() -> None:
    """Neither allowed nor protected is still a refusal, not a default-allow."""
    with pytest.raises(ExperimentBoundaryError, match="not a declared"):
        assert_presentation_only("something_new")


def test_the_two_surface_sets_do_not_overlap() -> None:
    assert ALLOWED_EXPERIMENT_SURFACES.isdisjoint(PROTECTED_FROM_EXPERIMENTS)


def test_exposures_are_deleted_with_the_guest(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    client.post("/v1/recommendations", json=CHECK_IN, headers=guest_headers)
    client.post(
        "/v1/experiments/exposures",
        json={"experiment_id": EXPLANATION_COPY_EXPERIMENT, "context": "c1"},
        headers=guest_headers,
    )
    assert client.delete("/v1/me/data", headers=guest_headers).status_code == 204
    assert client.get("/v1/me/export", headers=guest_headers).status_code == 404
