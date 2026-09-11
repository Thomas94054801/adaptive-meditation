#!/usr/bin/env python3
"""Offline rule-set comparator.

Runs two rule sets over the full reachable state space and reports what changed.
This is the "offline comparison" step of the Program002 loop: evidence informs a
human, a human approves a versioned rule set, and nothing here writes to
production.

Both rule sets run against the *same* catalog, so a diff isolates the rule
change rather than mixing in a knowledge change.

No network access and no model of any kind. It reads the knowledge files and the
rule tables and nothing else.

Usage:
    python scripts/compare_rulesets.py --baseline v1 --candidate v2
    python scripts/compare_rulesets.py --baseline v1 --candidate v2 --json
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.practice.catalog import KnowledgeCatalog, load_catalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.recommendation.rules_v2 import PRACTICE_ORDER
from app.domain.recommendation.rulesets import build_rule_set
from app.domain.state.models import AVAILABLE_MINUTES, ExperienceLevel, Goal, StateVector

# Low, middle and high: enough for the energy rule to fire in reduced mode.
QUICK_ENERGIES: tuple[int, ...] = (0, 5, 9)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_DIR = REPO_ROOT / "knowledge"


def iter_states(full: bool = True) -> Iterator[StateVector]:
    """Enumerate the reachable state space.

    ``full`` enumerates energy 0..10. Program001 pinned energy because no rule
    read it; v2 does, so pinning it would report a state space the rules do not
    actually live in.

    The reduced mode samples low, middle and high energy rather than pinning a
    single value: pinning 5 hid the energy rule entirely, and a comparison that
    cannot see a declared rule is worse than no comparison.
    """
    energies = range(11) if full else QUICK_ENERGIES
    for goal, stress, energy, mental, sleepy, minutes, level in itertools.product(
        Goal, range(11), energies, range(11), range(11), AVAILABLE_MINUTES, ExperienceLevel
    ):
        yield StateVector(
            goal=goal,
            experience_level=level,
            available_minutes=minutes,  # type: ignore[arg-type]
            stress=stress,
            energy=energy,
            mental_activity=mental,
            sleepiness=sleepy,
        )


def state_space_size(full: bool = True) -> int:
    energies = 11 if full else len(QUICK_ENERGIES)
    return len(Goal) * 11 * energies * 11 * 11 * len(AVAILABLE_MINUTES) * len(ExperienceLevel)


@dataclass
class Report:
    baseline: str
    candidate: str
    knowledge_version: int
    total_states: int = 0
    changed: int = 0
    practice_baseline: Counter[str] = field(default_factory=Counter)
    practice_candidate: Counter[str] = field(default_factory=Counter)
    duration_baseline: Counter[int] = field(default_factory=Counter)
    duration_candidate: Counter[int] = field(default_factory=Counter)
    density_baseline: Counter[str] = field(default_factory=Counter)
    density_candidate: Counter[str] = field(default_factory=Counter)
    reason_baseline: Counter[str] = field(default_factory=Counter)
    reason_candidate: Counter[str] = field(default_factory=Counter)
    transitions: Counter[str] = field(default_factory=Counter)

    @property
    def changed_percentage(self) -> float:
        return round(100.0 * self.changed / self.total_states, 4) if self.total_states else 0.0

    def unreachable(self, which: str) -> list[str]:
        seen = self.practice_baseline if which == "baseline" else self.practice_candidate
        return [p.value for p in PRACTICE_ORDER if seen[p.value] == 0]

    def as_dict(self) -> dict[str, object]:
        return {
            "baseline_rule_set": self.baseline,
            "candidate_rule_set": self.candidate,
            "knowledge_version": self.knowledge_version,
            "total_states_compared": self.total_states,
            "changed_recommendations": self.changed,
            "changed_percentage": self.changed_percentage,
            "practice_distribution": {
                "baseline": dict(self.practice_baseline),
                "candidate": dict(self.practice_candidate),
            },
            "duration_distribution": {
                "baseline": dict(sorted(self.duration_baseline.items())),
                "candidate": dict(sorted(self.duration_candidate.items())),
            },
            "guidance_density_distribution": {
                "baseline": dict(sorted(self.density_baseline.items())),
                "candidate": dict(sorted(self.density_candidate.items())),
            },
            "reason_code_changes": {
                "baseline": dict(sorted(self.reason_baseline.items())),
                "candidate": dict(sorted(self.reason_candidate.items())),
            },
            "practice_transitions": dict(sorted(self.transitions.items())),
            "unreachable_practices": {
                "baseline": self.unreachable("baseline"),
                "candidate": self.unreachable("candidate"),
            },
        }


def compare(
    catalog: KnowledgeCatalog, baseline: str, candidate: str, *, full: bool = True
) -> Report:
    base_engine = RecommendationEngine(catalog, build_rule_set(baseline))
    cand_engine = RecommendationEngine(catalog, build_rule_set(candidate))
    report = Report(
        baseline=baseline, candidate=candidate, knowledge_version=catalog.knowledge_version
    )

    for state in iter_states(full):
        report.total_states += 1
        a = base_engine.recommend_for_state(state)
        b = cand_engine.recommend_for_state(state)

        report.practice_baseline[a.practice_id] += 1
        report.practice_candidate[b.practice_id] += 1
        report.duration_baseline[a.duration_minutes] += 1
        report.duration_candidate[b.duration_minutes] += 1
        report.density_baseline[f"{a.guidance_density:.2f}"] += 1
        report.density_candidate[f"{b.guidance_density:.2f}"] += 1
        for code in a.reason_codes:
            report.reason_baseline[code] += 1
        for code in b.reason_codes:
            report.reason_candidate[code] += 1

        if a.practice_id != b.practice_id:
            report.changed += 1
            report.transitions[f"{a.practice_id} -> {b.practice_id}"] += 1

    return report


def render(report: Report) -> str:
    data = report.as_dict()
    lines = [
        f"rule set {report.baseline} -> {report.candidate}  "
        f"(knowledge v{report.knowledge_version})",
        "",
        f"total states compared      {report.total_states:,}",
        f"changed recommendations    {report.changed:,}",
        f"changed percentage         {report.changed_percentage}%",
        "",
        "practice distribution",
    ]
    for practice in PRACTICE_ORDER:
        name = practice.value
        before = report.practice_baseline[name]
        after = report.practice_candidate[name]
        lines.append(f"  {name:22s} {before:>8,} -> {after:>8,}  ({after - before:+,})")

    lines += ["", "duration distribution"]
    for minutes in sorted(set(report.duration_baseline) | set(report.duration_candidate)):
        lines.append(
            f"  {minutes:>2} min                {report.duration_baseline[minutes]:>8,} -> "
            f"{report.duration_candidate[minutes]:>8,}"
        )

    lines += ["", "guidance density distribution"]
    for density in sorted(set(report.density_baseline) | set(report.density_candidate)):
        lines.append(
            f"  {density:22s} {report.density_baseline[density]:>8,} -> "
            f"{report.density_candidate[density]:>8,}"
        )

    lines += ["", "reason code changes"]
    for code in sorted(set(report.reason_baseline) | set(report.reason_candidate)):
        lines.append(
            f"  {code:22s} {report.reason_baseline[code]:>8,} -> "
            f"{report.reason_candidate[code]:>8,}"
        )

    if report.transitions:
        lines += ["", "practice transitions"]
        for transition, count in sorted(report.transitions.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {transition:48s} {count:>8,}")

    unreachable = data["unreachable_practices"]
    assert isinstance(unreachable, dict)
    lines += [
        "",
        f"unreachable practices (baseline)   {unreachable['baseline'] or 'none'}",
        f"unreachable practices (candidate)  {unreachable['candidate'] or 'none'}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="1", help="baseline rule set version")
    parser.add_argument("--candidate", default="2", help="candidate rule set version")
    parser.add_argument(
        "--knowledge-version", type=int, default=2, help="catalog both rule sets run against"
    )
    parser.add_argument("--knowledge-dir", type=Path, default=DEFAULT_KNOWLEDGE_DIR)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--quick", action="store_true", help="sample energy, for a fast smoke comparison"
    )
    args = parser.parse_args()

    # "v1"/"v2" and "1"/"2" both accepted; the flag reads better with the v.
    baseline = args.baseline.lstrip("vV")
    candidate = args.candidate.lstrip("vV")

    catalog = load_catalog(args.knowledge_dir, args.knowledge_version)
    report = compare(catalog, baseline, candidate, full=not args.quick)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
