#!/usr/bin/env python3
"""Latency benchmark for the paths the SDD sets budgets for.

Committed rather than ad hoc, because "it was 1.4 ms on my machine last month"
is not a baseline anyone can check.

Two modes, deliberately separate:

``--mode benchmark``
    A measurement. Reports p50/p95 and enforces the product budgets strictly.
    For a controlled machine - never a shared CI runner.

``--mode ci-guard``
    A regression guard for noisy hosted runners. It does not pretend hosted
    latency is a stable benchmark; its only job is to catch a gross regression
    - a path that starts doing a query per segment - without failing on runner
    hiccups. A single breach is re-measured once, immediately, for the failing
    path only; a second breach fails. Anything past ten times its budget fails
    outright, whatever the mode, and is never excused as variance.

The product budgets are the same in both modes. What differs is how much
evidence a breach needs before it is called a regression.

The script names only the environment it is told about. A hosted runner is not
a local workstation and is not OCI, and nothing here says otherwise.

Usage:
    TEST_DATABASE_URL=postgresql+psycopg://... python scripts/benchmark_paths.py
    ... --mode ci-guard --environment github-hosted-ci --runs 30
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
from enum import StrEnum
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.domain.personalization import EVIDENCE_CAP  # noqa: E402
from app.main import create_app  # noqa: E402
from app.persistence.repositories import SessionRepository  # noqa: E402
from app.persistence.seed import seed_sparse_history  # noqa: E402
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


# A measurement this far past its budget is not runner noise. Ten times is
# wide enough that a GC pause or a noisy neighbour cannot reach it, and narrow
# enough that a query-per-row regression cannot hide inside it.
CATASTROPHIC_MULTIPLIER = 10

MODE_BENCHMARK = "benchmark"
MODE_CI_GUARD = "ci-guard"


class Verdict(StrEnum):
    PASS = "PASS"
    PASS_AFTER_TRANSIENT_CONFIRMATION = "PASS_AFTER_TRANSIENT_CONFIRMATION"
    FAIL_CONFIRMED = "FAIL_CONFIRMED"
    FAIL_CATASTROPHIC = "FAIL_CATASTROPHIC"

    @property
    def passed(self) -> bool:
        return self in {Verdict.PASS, Verdict.PASS_AFTER_TRANSIENT_CONFIRMATION}


@dataclass(slots=True)
class Evaluation:
    """One path's outcome, with the evidence that produced it."""

    result: Result
    mode: str
    initial: str
    confirmation: Result | None
    final: Verdict

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            **self.result.as_dict(),
            "mode": self.mode,
            "initial_verdict": self.initial,
            "final_verdict": self.final.value,
        }
        if self.confirmation is not None:
            payload["confirmation_p50_ms"] = round(self.confirmation.p50, 3)
            payload["confirmation_p95_ms"] = round(self.confirmation.p95, 3)
        return payload


def catastrophic_ceiling(budget_ms: float) -> float:
    return budget_ms * CATASTROPHIC_MULTIPLIER


def evaluate(result: Result, mode: str, confirm: Callable[[], Result] | None = None) -> Evaluation:
    """Decide a path's verdict. Pure: timings come in, a verdict comes out.

    ``confirm`` re-measures the same path and is called at most once, only in
    ci-guard mode, only after an ordinary-budget breach. It is a callable
    rather than a result so a test can inject the confirmation and so the real
    script only pays for it when it is needed.
    """
    ceiling = catastrophic_ceiling(result.budget_ms)
    if result.p95 >= ceiling:
        # An order of magnitude over is a regression in any mode. It is not
        # re-measured, because a second look could only excuse it.
        return Evaluation(result, mode, "catastrophic", None, Verdict.FAIL_CATASTROPHIC)
    if result.within_budget:
        return Evaluation(result, mode, "ok", None, Verdict.PASS)
    if mode != MODE_CI_GUARD or confirm is None:
        # Benchmark mode is strict: a breach is a breach.
        return Evaluation(result, mode, "over", None, Verdict.FAIL_CONFIRMED)

    confirmation = confirm()
    if confirmation.p95 >= ceiling:
        return Evaluation(result, mode, "over", confirmation, Verdict.FAIL_CATASTROPHIC)
    if confirmation.within_budget:
        # The first measurement was the runner, not the code. Recorded as such
        # rather than silently passed, so a pattern of transients stays visible.
        return Evaluation(
            result, mode, "over", confirmation, Verdict.PASS_AFTER_TRANSIENT_CONFIRMATION
        )
    return Evaluation(result, mode, "over", confirmation, Verdict.FAIL_CONFIRMED)


def measure(name: str, budget_ms: float, call: Callable[[], object], runs: int) -> Result:
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


@dataclass(slots=True)
class Bench:
    """A live client plus the paths it can time, so one path can be re-timed."""

    client: TestClient
    specs: list[tuple[str, float, Callable[[], object]]]
    runs: int

    def measure_all(self, only: str | None = None) -> list[Result]:
        return [
            measure(name, budget, call, self.runs)
            for name, budget, call in self.specs
            if only is None or only in name
        ]

    def measure_one(self, name: str) -> Result:
        for spec_name, budget, call in self.specs:
            if spec_name == name:
                return measure(spec_name, budget, call, self.runs)
        raise KeyError(name)


def open_bench(database_url: str, runs: int) -> tuple[TestClient, Bench]:
    """Build the client and the path specs. The caller owns the client context."""
    client = build_client(database_url)
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

        # Program005: a guest whose history is mostly other practices and
        # abandoned runs, with a handful of completed matches. Sparse on
        # purpose: the number then reflects the index walking past rows that
        # do not match, not the cap cutting a dense history short.
        database = client.app.state.database
        sparse_guest, sparse_practice = seed_sparse_history(database, rows=400, matches=5)

        def familiarity_query() -> None:
            with database.session() as session:
                SessionRepository(session).completed_count(
                    sparse_guest, sparse_practice, cap=EVIDENCE_CAP
                )

        specs: list[tuple[str, float, Callable[[], object]]] = [
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
            # Program005. A controlled-environment design target; on the
            # hosted runner it guards for an order of magnitude like the rest.
            ("familiarity context query", 50, familiarity_query),
        ]

        return client, Bench(client=client, specs=specs, runs=runs)


def run(database_url: str, runs: int, only: str | None = None) -> list[Result]:
    """Measure each path, optionally filtered by a substring of its name.

    The filter exists so the same script can measure an older commit, which has
    only some of these paths. Comparing a baseline measured by a different
    script is comparing two harnesses, not two commits.
    """
    client, bench = open_bench(database_url, runs)
    with client:
        return bench.measure_all(only)


def _confirmer(bench: Bench, name: str) -> Callable[[], Result]:
    """Bind one path's re-measurement. Only called if the first pass breached."""

    def confirm() -> Result:
        return bench.measure_one(name)

    return confirm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--only", help="measure only paths whose name contains this")
    parser.add_argument(
        "--mode",
        choices=(MODE_BENCHMARK, MODE_CI_GUARD),
        default=MODE_BENCHMARK,
        help="benchmark: strict budgets; ci-guard: one confirmation before failing",
    )
    parser.add_argument(
        "--environment",
        default="local",
        help="a label for where this ran, e.g. github-hosted-ci; never inferred",
    )
    args = parser.parse_args()

    database_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        print("set TEST_DATABASE_URL to a migrated database", file=sys.stderr)
        return 2

    client, bench = open_bench(database_url, args.runs)
    with client:
        results = bench.measure_all(args.only)
        evaluations = [
            evaluate(result, args.mode, confirm=_confirmer(bench, result.name))
            for result in results
        ]

    if args.json:
        print(json.dumps([e.as_dict() for e in evaluations], indent=2))
        return 0 if all(e.final.passed for e in evaluations) else 1

    print()
    print("PERFORMANCE MEASUREMENT")
    print(f"environment = {args.environment}")
    print(f"mode        = {args.mode}")
    print(f"{args.runs} runs per path, after one untimed warm-up.")
    if args.mode == MODE_CI_GUARD:
        print(
            "ci-guard: a breach is re-measured once for that path only; a second "
            f"breach fails. Anything past {CATASTROPHIC_MULTIPLIER}x budget fails "
            "outright."
        )
    print()
    print(f"{'path':<34}{'p50':>9}{'p95':>9}{'budget':>9}  initial   final")
    print("-" * 96)
    for e in evaluations:
        print(
            f"{e.result.name:<34}{e.result.p50:>8.3f}ms{e.result.p95:>8.3f}ms"
            f"{e.result.budget_ms:>8.0f}ms  {e.initial:<9} {e.final.value}"
        )
        if e.confirmation is not None:
            print(
                f"{'  confirmation':<34}{e.confirmation.p50:>8.3f}ms"
                f"{e.confirmation.p95:>8.3f}ms"
            )
    print()
    return 0 if all(e.final.passed for e in evaluations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
