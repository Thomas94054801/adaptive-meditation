"""The offline rule-set comparator.

The comparator is the step between "we have outcome evidence" and "we approve a
new rule set", so its output is the thing a human reads before changing
production. If it under-reports a change, the approval is worthless.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.domain.practice.catalog import KnowledgeCatalog

from .conftest import BACKEND_ROOT

sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from compare_rulesets import (  # type: ignore[import-not-found]
    compare,
    iter_states,
    render,
    state_space_size,
)

# The declared transitions from SDD_PROGRAM002 section 2.23. This is the golden
# output: an undeclared transition fails here rather than being noticed later.
DECLARED_TRANSITIONS = {
    "breath_awareness -> mindful_walking",
    "feeling_tone -> kindness",
    "breath_awareness -> body_awareness",
    "body_awareness -> kindness",
}


@pytest.fixture(scope="module")
def quick_report(catalog: KnowledgeCatalog):  # type: ignore[no-untyped-def]
    """Energy sampled at low/middle/high, for assertions not needing the full space."""
    return compare(catalog, "1", "2", full=False)


def test_state_space_size_matches_the_enumeration() -> None:
    assert state_space_size(full=True) == 1_317_690
    assert sum(1 for _ in iter_states(full=True)) == state_space_size(full=True)
    assert state_space_size(full=False) == 359_370


def test_the_comparator_reports_the_whole_space(catalog: KnowledgeCatalog) -> None:
    report = compare(catalog, "1", "2", full=False)
    assert report.total_states == 359_370
    assert report.baseline == "1"
    assert report.candidate == "2"
    assert report.knowledge_version == 2


def test_a_rule_set_compared_with_itself_reports_no_change(
    catalog: KnowledgeCatalog,
) -> None:
    """The comparator's own null hypothesis."""
    report = compare(catalog, "2", "2", full=False)
    assert report.changed == 0
    assert report.changed_percentage == 0.0
    assert report.transitions == {}


def test_only_declared_transitions_appear(quick_report) -> None:  # type: ignore[no-untyped-def]
    assert set(quick_report.transitions) <= DECLARED_TRANSITIONS


def test_unreachable_practices_are_reported_for_both_rule_sets(
    quick_report,  # type: ignore[no-untyped-def]
) -> None:
    """Program001's two gaps, and their absence under v2."""
    assert set(quick_report.unreachable("baseline")) == {"kindness", "mindful_walking"}
    assert quick_report.unreachable("candidate") == []


def test_distributions_cover_every_state(quick_report) -> None:  # type: ignore[no-untyped-def]
    total = quick_report.total_states
    assert sum(quick_report.practice_baseline.values()) == total
    assert sum(quick_report.practice_candidate.values()) == total
    assert sum(quick_report.duration_baseline.values()) == total
    assert sum(quick_report.duration_candidate.values()) == total
    assert sum(quick_report.density_baseline.values()) == total
    assert sum(quick_report.density_candidate.values()) == total


def test_duration_distribution_is_unchanged(quick_report) -> None:  # type: ignore[no-untyped-def]
    """v2 changed practice selection, not the duration policy."""
    assert quick_report.duration_baseline == quick_report.duration_candidate


def test_no_practice_dominates_the_candidate_distribution(
    quick_report,  # type: ignore[no-untyped-def]
) -> None:
    """The defect the comparator caught on its first run.

    body_awareness had reached 76% of all states, which is not a recommender.
    """
    total = quick_report.total_states
    for practice, count in quick_report.practice_candidate.items():
        assert count / total < 0.5, f"{practice} wins {count / total:.0%} of states"


def test_the_report_renders(quick_report) -> None:  # type: ignore[no-untyped-def]
    text = render(quick_report)
    assert "total states compared" in text
    assert "unreachable practices (candidate)" in text
    assert "mindful_walking" in text


def test_the_report_serializes_every_required_section(
    quick_report,  # type: ignore[no-untyped-def]
) -> None:
    data = quick_report.as_dict()
    for key in (
        "total_states_compared",
        "changed_recommendations",
        "changed_percentage",
        "practice_distribution",
        "duration_distribution",
        "guidance_density_distribution",
        "reason_code_changes",
        "unreachable_practices",
    ):
        assert key in data, key


def test_the_comparator_runs_as_a_script_without_network() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "compare_rulesets.py"),
            "--baseline",
            "v1",
            "--candidate",
            "v2",
            "--quick",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"changed_recommendations"' in completed.stdout
