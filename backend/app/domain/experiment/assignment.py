"""Deterministic experiment assignment.

The same guest and experiment must yield the same variant on every call, in
every process, forever. Randomising per request would make an assignment
unreproducible the moment it mattered - when reading back why a particular
session got the arm it got.

An experiment may vary presentation and ranking weights. It may never cross a
safety invariant: it cannot bypass a contraindication, exceed a duration
envelope, breach a guidance-density range, or surface a practice below its
minimum experience. Those are enforced in the engine, not here, and this module
has no way to reach them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# SHA-256 of "guest_id:experiment_id". Stable across processes and releases,
# unlike Python's salted built-in hash().
HASH_BUCKETS = 10_000


class ExperimentError(ValueError):
    """Raised when an experiment definition is unusable."""


@dataclass(frozen=True, slots=True)
class Experiment:
    """A named split with fixed, ordered variants."""

    experiment_id: str
    variants: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.variants) < 2:
            raise ExperimentError(f"experiment {self.experiment_id!r} needs 2+ variants")
        if len(set(self.variants)) != len(self.variants):
            raise ExperimentError(f"experiment {self.experiment_id!r} has duplicate variants")


@dataclass(frozen=True, slots=True)
class Assignment:
    experiment_id: str
    variant: str
    assignment_key: str

    def as_dict(self) -> dict[str, str]:
        return {
            "experiment_id": self.experiment_id,
            "variant": self.variant,
            "assignment_key": self.assignment_key,
        }


def assignment_key(guest_id: str, experiment_id: str) -> str:
    """The stable key an assignment is derived from, recorded alongside it."""
    return hashlib.sha256(f"{guest_id}:{experiment_id}".encode()).hexdigest()


def bucket_of(key: str) -> int:
    """Map an assignment key into a fixed number of buckets."""
    return int(key[:8], 16) % HASH_BUCKETS


def assign(guest_id: str, experiment: Experiment) -> Assignment:
    """Assign a guest to a variant. Pure, and stable forever."""
    key = assignment_key(guest_id, experiment.experiment_id)
    variant = experiment.variants[bucket_of(key) % len(experiment.variants)]
    return Assignment(experiment.experiment_id, variant, key)


# Experiments defined for Program002. Empty variants lists are rejected at
# import, so a malformed definition cannot reach production.
REGISTRY: dict[str, Experiment] = {
    experiment.experiment_id: experiment
    for experiment in (
        # Presentation only: how the recommendation reason is phrased.
        Experiment("reason_phrasing_v1", ("concise", "expanded")),
    )
}


def get_experiment(experiment_id: str) -> Experiment:
    try:
        return REGISTRY[experiment_id]
    except KeyError:
        raise ExperimentError(f"unknown experiment {experiment_id!r}") from None
