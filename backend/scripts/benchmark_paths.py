#!/usr/bin/env python3
"""Latency benchmark for the paths the SDD sets budgets for.

Committed rather than ad hoc, because "it was 1.4 ms on my machine last month"
is not a baseline anyone can check. Every number this prints is a local
workstation measurement and must never be reported as an OCI figure.

Usage:
    TEST_DATABASE_URL=postgresql+psycopg://... python scripts/benchmark_paths.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402

CHECK_IN = {
    "goal": "overthinking",
    "stress": 8,
    "energy": 5,
    "mental_activity": 9,
    "sleepiness": 2,
    "available_minutes": 10,
    "experience_level": "beginner",
}


@dataclass(slots=True)
class Result:
    name: str
    budget_ms: float
    samples: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return statistics.median(self.samples)

    @property
    def p95(self) -> float:
        ordered = sorted(self.samples)
        index = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return ordered[index]

    @property
    def within_budget(self) -> bool:
        return self.p95 < self.budget_ms

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.name,
            "p50_ms": round(self.p50, 3),
            "p95_ms": round(self.p95, 3),
            "budget_ms": self.budget_ms,
            "within_budget": self.within_budget,
            "samples": len(self.samples),
        }


def measure(name: str, budget_ms: float, call: Callable[[], None], runs: int) -> Result:
    # One untimed call so import, connection and query-plan costs do not land in
    # the first sample and make a warm path look cold.
    call()
    result = Result(name=name, budget_ms=budget_ms)
    for _ in range(runs):
        started = time.perf_counter()
        call()
        result.samples.append((time.perf_counter() - started) * 1000)
    return result


def build_client(database_url: str) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url=database_url,
        knowledge_dir=BACKEND_ROOT.parent / "knowledge",
        ai_provider="null",
        ai_api_key=None,
    )
    return TestClient(create_app(settings))


def run(database_url: str, runs: int, only: str | None = None) -> list[Result]:
    """Measure each path, optionally filtered by a substring of its name.

    The filter exists so the same script can measure an older commit, which has
    only some of these paths. Comparing a baseline measured by a different
    script is comparing two harnesses, not two commits.
    """
    client = build_client(database_url)
    results: list[Result] = []
    guest = {"X-Guest-Id": str(uuid.uuid4())}

    with client:
        check_in_id = client.post("/v1/check-ins", json=CHECK_IN, headers=guest).json()["id"]
        session_id = client.post(
            "/v1/sessions", json={"check_in_id": check_in_id}, headers=guest
        ).json()["id"]

        counter = {"n": 0}

        def append_batch() -> None:
            # Twenty events, about one real session's worth.
            start = counter["n"] * 100
            counter["n"] += 1
            client.post(
                f"/v1/sessions/{session_id}/events",
                json={
                    "events": [
                        {
                            "sequence": start + i,
                            "event_type": "segment_started",
                            "elapsed_ms": i * 1000,
                        }
                        for i in range(20)
                    ]
                },
                headers=guest,
            )

        specs: list[tuple[str, float, Callable[[], None]]] = [
            # The Program003 baseline paths, measured the same way so the
            # comparison is like for like.
            (
                "recommendation API (no guest)",
                150,
                lambda: client.post("/v1/recommendations", json=CHECK_IN),
            ),
            (
                "recommendation API (with guest)",
                150,
                lambda: client.post("/v1/recommendations", json=CHECK_IN, headers=guest),
            ),
            (
                "history API",
                300,
                lambda: client.get("/v1/sessions/history?limit=20", headers=guest),
            ),
            # Program004 paths.
            (
                "session create (plan v1 + v2)",
                250,
                lambda: client.post(
                    "/v1/sessions", json={"check_in_id": check_in_id}, headers=guest
                ),
            ),
            (
                "prepare (render manifest)",
                250,
                lambda: client.post(f"/v1/sessions/{session_id}/prepare", headers=guest),
            ),
            ("event batch ingest (20)", 120, append_batch),
            (
                "playback state read",
                120,
                lambda: client.get(f"/v1/sessions/{session_id}/playback", headers=guest),
            ),
        ]

        for name, budget, call in specs:
            if only is not None and only not in name:
                continue
            results.append(measure(name, budget, call, runs))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--only", help="measure only paths whose name contains this")
    args = parser.parse_args()

    database_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        print("set TEST_DATABASE_URL to a migrated database", file=sys.stderr)
        return 2

    results = run(database_url, args.runs, args.only)

    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
        return 0

    print()
    print("LOCAL WORKSTATION MEASUREMENT. NOT AN OCI MEASUREMENT.")
    print(f"{args.runs} runs per path, after one untimed warm-up.")
    print()
    print(f"{'path':<34}{'p50':>9}{'p95':>9}{'budget':>9}  ")
    print("-" * 64)
    for result in results:
        mark = "ok" if result.within_budget else "OVER"
        print(
            f"{result.name:<34}{result.p50:>8.3f}ms{result.p95:>8.3f}ms"
            f"{result.budget_ms:>8.0f}ms  {mark}"
        )
    print()
    return 0 if all(r.within_budget for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
