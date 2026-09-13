#!/usr/bin/env python3
"""Offline outcome report.

The first consumer of session_outcome_score. It reads outcome evidence and
prints an aggregate summary for a human to look at.

What it deliberately does not do: change anything. The pipeline is

    outcome -> evidence -> offline analysis -> human review -> future rule set

and never

    outcome -> automatic production mutation

Nothing here writes to the database, and no production rule reads its output. A
recommender that retuned itself from its own outcome data would make every
stored rule_set_version meaningless, which is the failure this shape avoids.

No clinical claim is made or implied. The measures are self-reported numbers
moving in a direction the product hoped for, aggregated. They are not evidence
of therapeutic effect, and small cells are marked rather than ranked.

Usage:
    python scripts/outcome_report.py
    python scripts/outcome_report.py --json
    python scripts/outcome_report.py --min-sample 30
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa

from app.persistence import models
from app.persistence.database import Database
from app.settings import Settings

# Below this many sessions a cell is reported but not ranked. A product
# analytics guard, not a significance test: it stops three sessions being read
# as a finding, and claims nothing about statistical power.
DEFAULT_MIN_SAMPLE = 20
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"

DISCLAIMER = (
    "Product analytics only. These are self-reported numbers, aggregated. "
    "They are not a clinical, diagnostic or therapeutic measure, and no claim "
    "of medical effect is made or implied."
)


@dataclass
class Cell:
    """One practice x goal group."""

    practice_id: str
    goal: str
    primary_measure: str | None = None
    sessions: int = 0
    completed: int = 0
    primary_deltas: list[int] = field(default_factory=list)
    helpfulness: list[int] = field(default_factory=list)
    outcome_scores: list[int] = field(default_factory=list)

    @property
    def completion_rate(self) -> float | None:
        if self.sessions == 0:
            return None
        return round(self.completed / self.sessions, 3)

    @property
    def sufficient(self) -> bool:
        return len(self.primary_deltas) >= _min_sample

    def quantiles(self) -> tuple[float | None, float | None, float | None]:
        """Median, p25, p75 of the primary measure."""
        values = sorted(self.primary_deltas)
        if not values:
            return None, None, None
        median = statistics.median(values)
        if len(values) < 4:
            # Quartiles of three points describe the three points, not a
            # distribution. Reported as absent rather than as a number.
            return median, None, None
        return (
            median,
            _percentile(values, 0.25),
            _percentile(values, 0.75),
        )

    def helpfulness_distribution(self) -> dict[int, int]:
        counts = {score: 0 for score in range(1, 6)}
        for value in self.helpfulness:
            if value in counts:
                counts[value] += 1
        return counts

    def as_dict(self) -> dict[str, object]:
        median, p25, p75 = self.quantiles()
        return {
            "practice_id": self.practice_id,
            "goal": self.goal,
            "primary_measure": self.primary_measure,
            "sessions": self.sessions,
            "sessions_with_outcome": len(self.primary_deltas),
            "completion_rate": self.completion_rate,
            "median_primary_outcome": median,
            "p25_primary_outcome": p25,
            "p75_primary_outcome": p75,
            "helpfulness_distribution": self.helpfulness_distribution(),
            "median_outcome_score": (
                statistics.median(self.outcome_scores) if self.outcome_scores else None
            ),
            "sufficient_sample": self.sufficient,
            "status": None if self.sufficient else INSUFFICIENT_SAMPLE,
        }


_min_sample = DEFAULT_MIN_SAMPLE


def _percentile(sorted_values: list[int], fraction: float) -> float:
    """Nearest-rank percentile. Deterministic and dependency-free."""
    if not sorted_values:
        raise ValueError("empty")
    index = max(0, min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1))))
    return float(sorted_values[index])


def collect(database: Database) -> list[Cell]:
    """Aggregate outcome evidence into practice x goal cells.

    Streams rows and accumulates per cell. The only thing that grows with the
    number of sessions is the per-cell delta lists, bounded by practices x goals
    (seven by six) rather than by session count in breadth.
    """
    cells: dict[tuple[str, str], Cell] = {}

    with database.session() as session:
        stmt = (
            sa.select(
                models.Session.recommendation,
                models.Session.status,
                models.CheckIn.goal,
                models.SessionFeedback.primary_measure,
                models.SessionFeedback.primary_delta,
                models.SessionFeedback.helpfulness,
                models.SessionFeedback.outcome_score,
            )
            .join(models.CheckIn, models.Session.check_in_id == models.CheckIn.id)
            .join(
                models.SessionFeedback,
                models.SessionFeedback.session_id == models.Session.id,
                isouter=True,
            )
        )
        for row in session.execute(stmt):
            recommendation = row.recommendation or {}
            practice_id = str(recommendation.get("practice_id", "unknown"))
            key = (practice_id, row.goal)
            cell = cells.setdefault(key, Cell(practice_id=practice_id, goal=row.goal))
            cell.sessions += 1
            if row.status == "completed":
                cell.completed += 1
            if row.primary_delta is not None:
                cell.primary_measure = row.primary_measure
                cell.primary_deltas.append(row.primary_delta)
            if row.helpfulness is not None:
                cell.helpfulness.append(row.helpfulness)
            if row.outcome_score is not None:
                cell.outcome_scores.append(row.outcome_score)

    return sorted(cells.values(), key=lambda c: (c.goal, c.practice_id))


def render(cells: list[Cell]) -> str:
    lines = [
        "Outcome report - practice x goal",
        "",
        DISCLAIMER,
        "",
        f"minimum sample for ranking: {_min_sample}",
        "",
        f"{'goal':<17}{'practice':<22}{'n':>5}{'outcome n':>11}"
        f"{'compl':>8}{'median':>9}{'p25':>7}{'p75':>7}  measure / status",
    ]
    for cell in cells:
        median, p25, p75 = cell.quantiles()
        status = "" if cell.sufficient else f"  {INSUFFICIENT_SAMPLE}"
        measure = cell.primary_measure or "-"
        lines.append(
            f"{cell.goal:<17}{cell.practice_id:<22}{cell.sessions:>5}"
            f"{len(cell.primary_deltas):>11}"
            f"{_fmt(cell.completion_rate):>8}{_fmt(median):>9}"
            f"{_fmt(p25):>7}{_fmt(p75):>7}  {measure}{status}"
        )

    ranked = [c for c in cells if c.sufficient]
    lines += ["", ""]
    if ranked:
        lines.append("Cells with enough sessions to compare:")
        for cell in sorted(ranked, key=lambda c: (c.quantiles()[0] or 0), reverse=True):
            median, _, _ = cell.quantiles()
            lines.append(
                f"  {cell.goal:<17}{cell.practice_id:<22}median {_fmt(median)} "
                f"({cell.primary_measure})"
            )
    else:
        lines.append(
            f"No cell reached {_min_sample} sessions with outcome data, so nothing "
            "is ranked. Raw values above stand on their own."
        )
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def main() -> int:
    global _min_sample
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--min-sample",
        type=int,
        default=DEFAULT_MIN_SAMPLE,
        help=f"sessions required before a cell is ranked (default {DEFAULT_MIN_SAMPLE})",
    )
    args = parser.parse_args()
    _min_sample = args.min_sample

    database = Database(Settings())
    try:
        cells = collect(database)
    finally:
        database.dispose()

    if args.json:
        print(
            json.dumps(
                {
                    "disclaimer": DISCLAIMER,
                    "min_sample": _min_sample,
                    "clinical_claim": False,
                    "cells": [cell.as_dict() for cell in cells],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
