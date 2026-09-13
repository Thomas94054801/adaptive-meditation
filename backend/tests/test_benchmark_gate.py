"""The performance guard's decision logic, with no timing in it.

Every case here injects samples. The question the guard answers is "given these
numbers, is this a regression?" and that question is deterministic; only the
numbers are noisy, and they are exactly what a hosted runner cannot be trusted
to produce twice.

Background: on a docs-only commit, the hosted runner reported event batch
ingest at p50 6.4 ms and p95 173 ms against a 120 ms budget, then 7.1 ms on the
identical tree one push later. With n=30, p95 is the second-largest sample, so
a couple of runner hiccups fail the gate outright. The confirmation rule exists
for that, and the catastrophic ceiling exists so it cannot be abused.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

import pytest


def _gate():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_paths.py"
    spec = importlib.util.spec_from_file_location("benchmark_paths", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_paths"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _gate()


def result(gate, samples: list[float], budget: float = 120.0):
    return gate.Result(name="event batch ingest (20)", budget_ms=budget, samples=samples)


def steady(value: float, n: int = 30) -> list[float]:
    return [value] * n


def with_hiccups(base: float, spikes: list[float], n: int = 30) -> list[float]:
    """Mostly `base`, with the given spikes somewhere in the run."""
    return steady(base, n - len(spikes)) + spikes


def confirmer(gate, samples: list[float]) -> tuple[Callable[[], object], list[int]]:
    """A confirmation that returns fixed samples and records being called."""
    calls: list[int] = []

    def confirm():
        calls.append(1)
        return result(gate, samples)

    return confirm, calls


# --------------------------------------------------------------------------- #
# p95 selection: the reason two hiccups are enough
# --------------------------------------------------------------------------- #


def test_p95_of_thirty_is_the_second_largest_sample(gate) -> None:
    """Not a hypothesis - the arithmetic the failure came from."""
    r = result(gate, with_hiccups(6.0, [173.0, 95.0]))
    assert r.p95 == 95.0
    r = result(gate, with_hiccups(6.0, [173.0, 173.0]))
    assert r.p95 == 173.0
    r = result(gate, with_hiccups(6.0, [173.0]))
    assert r.p95 == 6.0, "one spike alone is absorbed; it takes two"


# --------------------------------------------------------------------------- #
# ci-guard verdicts
# --------------------------------------------------------------------------- #


def test_initial_pass_is_pass_without_confirmation(gate) -> None:
    confirm, calls = confirmer(gate, steady(6.0))
    e = gate.evaluate(result(gate, steady(6.0)), gate.MODE_CI_GUARD, confirm)
    assert e.final is gate.Verdict.PASS
    assert e.initial == "ok"
    assert e.confirmation is None
    assert calls == [], "a passing path is not re-measured"


def test_the_observed_hosted_failure_becomes_a_confirmed_transient(gate) -> None:
    """The exact shape from run 34756914955: p50 6.4, p95 173, budget 120."""
    first = result(gate, with_hiccups(6.44, [173.113, 150.0]))
    assert first.p95 == 150.0
    assert not first.within_budget

    confirm, calls = confirmer(gate, steady(7.058))
    e = gate.evaluate(first, gate.MODE_CI_GUARD, confirm)

    assert e.final is gate.Verdict.PASS_AFTER_TRANSIENT_CONFIRMATION
    assert e.initial == "over"
    assert calls == [1], "exactly one confirmation, for this path only"
    assert e.confirmation is not None
    assert e.confirmation.p95 == 7.058
    assert e.final.passed


def test_a_breach_confirmed_by_the_second_measurement_fails(gate) -> None:
    first = result(gate, steady(140.0))
    confirm, calls = confirmer(gate, steady(135.0))
    e = gate.evaluate(first, gate.MODE_CI_GUARD, confirm)

    assert e.final is gate.Verdict.FAIL_CONFIRMED
    assert calls == [1]
    assert not e.final.passed


def test_a_catastrophic_initial_breach_fails_without_confirmation(gate) -> None:
    """Ten times over is a regression, and a second look could only excuse it."""
    first = result(gate, steady(1300.0))  # budget 120 -> ceiling 1200
    confirm, calls = confirmer(gate, steady(6.0))
    e = gate.evaluate(first, gate.MODE_CI_GUARD, confirm)

    assert e.final is gate.Verdict.FAIL_CATASTROPHIC
    assert e.initial == "catastrophic"
    assert calls == [], "the confirmation is never consulted"


def test_a_catastrophic_confirmation_is_not_a_transient(gate) -> None:
    first = result(gate, steady(140.0))
    confirm, _ = confirmer(gate, steady(5000.0))
    e = gate.evaluate(first, gate.MODE_CI_GUARD, confirm)
    assert e.final is gate.Verdict.FAIL_CATASTROPHIC


def test_the_ceiling_is_exactly_ten_times_the_budget(gate) -> None:
    assert gate.CATASTROPHIC_MULTIPLIER == 10
    assert gate.catastrophic_ceiling(120.0) == 1200.0
    # Just under the ceiling is an ordinary breach, which gets its confirmation.
    first = result(gate, steady(1199.0))
    confirm, calls = confirmer(gate, steady(6.0))
    e = gate.evaluate(first, gate.MODE_CI_GUARD, confirm)
    assert e.final is gate.Verdict.PASS_AFTER_TRANSIENT_CONFIRMATION
    assert calls == [1]


# --------------------------------------------------------------------------- #
# benchmark mode stays strict
# --------------------------------------------------------------------------- #


def test_benchmark_mode_fails_an_ordinary_breach_with_no_confirmation(gate) -> None:
    """A measurement is a measurement. The confirmation rule is for runners."""
    first = result(gate, steady(125.0))
    confirm, calls = confirmer(gate, steady(6.0))
    e = gate.evaluate(first, gate.MODE_BENCHMARK, confirm)

    assert e.final is gate.Verdict.FAIL_CONFIRMED
    assert e.confirmation is None
    assert calls == [], "benchmark mode never re-measures"


def test_benchmark_mode_passes_within_budget(gate) -> None:
    e = gate.evaluate(result(gate, steady(6.0)), gate.MODE_BENCHMARK)
    assert e.final is gate.Verdict.PASS


# --------------------------------------------------------------------------- #
# the budgets themselves are untouched
# --------------------------------------------------------------------------- #


def test_the_product_budgets_are_unchanged(gate) -> None:
    """Stabilising the guard must not have moved the targets it guards."""
    source = (Path(__file__).resolve().parents[1] / "scripts" / "benchmark_paths.py").read_text()
    expected = {
        '"recommendation API (no guest)",\n                150,': True,
        '"recommendation API (with guest)",\n                150,': True,
        '"history API",\n                300,': True,
        '"session create (plan v1 + v2)",\n                250,': True,
        '"prepare (render manifest)",\n                250,': True,
        '("event batch ingest (20)", 120, append_batch)': True,
        '"playback state read",\n                120,': True,
    }
    for snippet in expected:
        assert snippet in source, f"budget line changed or moved: {snippet!r}"


def test_evaluation_serialises_its_evidence(gate) -> None:
    first = result(gate, with_hiccups(6.0, [173.0, 150.0]))
    confirm, _ = confirmer(gate, steady(7.0))
    payload = gate.evaluate(first, gate.MODE_CI_GUARD, confirm).as_dict()
    assert payload["mode"] == "ci-guard"
    assert payload["initial_verdict"] == "over"
    assert payload["final_verdict"] == "PASS_AFTER_TRANSIENT_CONFIRMATION"
    assert payload["confirmation_p95_ms"] == 7.0
    assert payload["budget_ms"] == 120.0
