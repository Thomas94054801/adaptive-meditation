"""The outcome report - SDD_PROGRAM003 sections 8, 9 and 44.

Seeds known sessions, runs the report, and checks the grouping, counts,
medians, direction and the minimum-sample guard.

The property these tests defend hardest: the report changes nothing. It is the
"offline analysis" step of a loop whose next step is a human, and a recommender
that retuned itself from its own outcome data would make every stored
rule_set_version meaningless.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.settings import Settings

from .conftest import BACKEND_ROOT

sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

import outcome_report  # type: ignore[import-not-found]
from outcome_report import (  # type: ignore[import-not-found]
    DEFAULT_MIN_SAMPLE,
    DISCLAIMER,
    INSUFFICIENT_SAMPLE,
    Cell,
    collect,
    render,
)

from app.persistence.database import Database

CHECK_IN = {
    "goal": "stress",
    "stress": 8,
    "energy": 5,
    "mental_activity": 4,
    "sleepiness": 3,
    "available_minutes": 10,
    "experience_level": "beginner",
}


def seed_session(
    client: TestClient,
    headers: dict[str, str],
    *,
    stress_after: int,
    helpfulness: int = 4,
    completed: bool = True,
) -> None:
    receipt = client.post("/v1/check-ins", json=CHECK_IN, headers=headers)
    assert receipt.status_code == 201
    session = client.post(
        "/v1/sessions", json={"check_in_id": receipt.json()["id"]}, headers=headers
    )
    assert session.status_code == 201
    response = client.post(
        f"/v1/sessions/{session.json()['id']}/feedback",
        json={
            "after_score": stress_after,
            "helpfulness": helpfulness,
            "completed": completed,
            "before_score": CHECK_IN["stress"],
            "stress_after": stress_after,
            "energy_after": 5,
            "mental_activity_after": 4,
            "sleepiness_after": 3,
            "completion_ratio": 1.0 if completed else 0.4,
        },
        headers=headers,
    )
    assert response.status_code == 204


@pytest.fixture
def seeded(client: TestClient, settings: Settings) -> Database:
    """25 sessions with a known stress reduction, plus one incomplete."""
    headers = {"X-Guest-Id": str(uuid.uuid4())}
    # 25 sessions, stress 8 -> 3, so primary_delta is 5 every time.
    for _ in range(25):
        seed_session(client, headers, stress_after=3)
    # One abandoned session, to exercise the completion rate.
    seed_session(client, headers, stress_after=6, completed=False)
    return Database(settings)


def cells_by_key(cells: list[Cell]) -> dict[tuple[str, str], Cell]:
    return {(cell.goal, cell.practice_id): cell for cell in cells}


def test_grouping_is_by_practice_and_goal(seeded: Database) -> None:
    cells = collect(seeded)
    seeded.dispose()
    keyed = cells_by_key(cells)
    assert ("stress", "body_awareness") in keyed
    cell = keyed[("stress", "body_awareness")]
    assert cell.sessions >= 26


def test_counts_and_completion_rate_are_correct(seeded: Database) -> None:
    cells = collect(seeded)
    seeded.dispose()
    cell = cells_by_key(cells)[("stress", "body_awareness")]
    # 25 completed out of 26 recorded for this guest's seeded set.
    assert cell.sessions >= 26
    assert cell.completion_rate is not None
    assert 0.0 < cell.completion_rate <= 1.0


def test_median_reflects_the_seeded_direction(seeded: Database) -> None:
    """Stress 8 -> 3 is a reduction of 5, and positive must mean improvement."""
    cells = collect(seeded)
    seeded.dispose()
    cell = cells_by_key(cells)[("stress", "body_awareness")]
    median, p25, p75 = cell.quantiles()
    assert cell.primary_measure == "stress_reduction"
    assert median is not None and median > 0
    assert p25 is not None and p75 is not None
    assert p25 <= median <= p75


def test_helpfulness_distribution_sums_to_the_sample(seeded: Database) -> None:
    cells = collect(seeded)
    seeded.dispose()
    cell = cells_by_key(cells)[("stress", "body_awareness")]
    distribution = cell.helpfulness_distribution()
    assert set(distribution) == {1, 2, 3, 4, 5}
    assert sum(distribution.values()) == len(cell.helpfulness)


def test_a_large_cell_is_ranked(seeded: Database) -> None:
    cells = collect(seeded)
    seeded.dispose()
    cell = cells_by_key(cells)[("stress", "body_awareness")]
    assert len(cell.primary_deltas) >= DEFAULT_MIN_SAMPLE
    assert cell.sufficient is True
    assert cell.as_dict()["status"] is None


def test_a_small_cell_is_marked_and_not_ranked(client: TestClient, settings: Settings) -> None:
    """Uses a goal no other test seeds.

    The report aggregates across every guest, which is correct, so a cell shared
    with another test's fixture would not be small. Isolating by goal keeps this
    test independent of execution order.
    """
    headers = {"X-Guest-Id": str(uuid.uuid4())}
    sleepy = dict(CHECK_IN, goal="sleep", sleepiness=8)
    for _ in range(3):
        receipt = client.post("/v1/check-ins", json=sleepy, headers=headers)
        session = client.post(
            "/v1/sessions", json={"check_in_id": receipt.json()["id"]}, headers=headers
        )
        client.post(
            f"/v1/sessions/{session.json()['id']}/feedback",
            json={
                "after_score": 4,
                "helpfulness": 4,
                "completed": True,
                "stress_after": 4,
                "energy_after": 5,
                "mental_activity_after": 4,
                "sleepiness_after": 9,
                "completion_ratio": 1.0,
            },
            headers=headers,
        )

    database = Database(settings)
    try:
        outcome_report._min_sample = 20
        cells = collect(database)
    finally:
        database.dispose()

    small = [c for c in cells if c.goal == "sleep" and len(c.primary_deltas) < 20]
    assert small, "expected at least one under-sampled cell"
    for cell in small:
        assert cell.sufficient is False
        assert cell.as_dict()["status"] == INSUFFICIENT_SAMPLE

    text = render(cells)
    assert INSUFFICIENT_SAMPLE in text


def test_quartiles_are_withheld_below_four_points() -> None:
    """Quartiles of three points describe the points, not a distribution."""
    cell = Cell(practice_id="x", goal="stress", primary_deltas=[1, 2, 3])
    median, p25, p75 = cell.quantiles()
    assert median == 2
    assert p25 is None and p75 is None


def test_the_report_makes_no_clinical_claim(seeded: Database) -> None:
    """The disclaimer may name clinical words in order to deny them.

    The body of the report may not use them at all, so the disclaimer is
    excluded from the scan rather than the words being waved through everywhere.
    """
    cells = collect(seeded)
    seeded.dispose()
    text = render(cells)
    body = text.replace(DISCLAIMER, "").lower()

    assert DISCLAIMER in text
    for banned in ("treat", "cure", "diagnos", "therap", "clinically proven", "efficacy"):
        assert banned not in body, banned

    # And the disclaimer must actually deny, not merely mention.
    lowered = DISCLAIMER.lower()
    assert "product analytics only" in lowered
    assert "not a clinical" in lowered
    assert "no claim of medical effect" in lowered


def test_the_report_is_read_only(seeded: Database, client: TestClient) -> None:
    """It must not change anything it reads.

    The pipeline is outcome -> evidence -> offline analysis -> human review.
    A report that wrote back would close that loop automatically, which is the
    one thing Program002 and Program003 both refuse to do.
    """
    before = collect(seeded)
    snapshot = [(c.goal, c.practice_id, c.sessions, len(c.primary_deltas)) for c in before]

    for _ in range(3):
        collect(seeded)

    after = collect(seeded)
    seeded.dispose()
    assert [(c.goal, c.practice_id, c.sessions, len(c.primary_deltas)) for c in after] == snapshot


def test_the_script_runs_and_emits_json(seeded: Database) -> None:
    seeded.dispose()
    completed = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "outcome_report.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr

    import json

    payload: dict[str, Any] = json.loads(completed.stdout)
    assert payload["clinical_claim"] is False
    assert payload["min_sample"] == DEFAULT_MIN_SAMPLE
    assert "cells" in payload


def test_the_minimum_sample_threshold_is_configurable(seeded: Database) -> None:
    cells = collect(seeded)
    seeded.dispose()
    outcome_report._min_sample = 1000
    assert all(not cell.sufficient for cell in cells)
    outcome_report._min_sample = DEFAULT_MIN_SAMPLE
