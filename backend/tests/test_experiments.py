"""Deterministic experiment assignment."""

from __future__ import annotations

import uuid
from collections import Counter

import pytest

from app.domain.experiment.assignment import (
    HASH_BUCKETS,
    REGISTRY,
    Assignment,
    Experiment,
    ExperimentError,
    assign,
    assignment_key,
    bucket_of,
    get_experiment,
)

EXPERIMENT = Experiment("test_split", ("control", "treatment"))


def test_the_same_guest_always_gets_the_same_variant() -> None:
    guest = str(uuid.uuid4())
    first = assign(guest, EXPERIMENT)
    for _ in range(200):
        assert assign(guest, EXPERIMENT) == first


def test_assignment_is_stable_across_processes() -> None:
    """A hardcoded expectation, so a change to the hashing fails loudly.

    Python's built-in hash is salted per process; if this module ever reached
    for it, this assertion is what would catch it.
    """
    guest = "11111111-2222-3333-4444-555555555555"
    key = assignment_key(guest, "reason_phrasing_v1")
    assert key == assignment_key(guest, "reason_phrasing_v1")
    assert len(key) == 64
    assert assign(guest, get_experiment("reason_phrasing_v1")).variant == "concise"


def test_the_assignment_key_is_recorded_with_the_variant() -> None:
    guest = str(uuid.uuid4())
    result = assign(guest, EXPERIMENT)
    assert result.assignment_key == assignment_key(guest, EXPERIMENT.experiment_id)
    assert result.experiment_id == EXPERIMENT.experiment_id


def test_different_experiments_assign_independently() -> None:
    guest = str(uuid.uuid4())
    a = assign(guest, Experiment("one", ("x", "y")))
    b = assign(guest, Experiment("two", ("x", "y")))
    assert a.assignment_key != b.assignment_key


def test_variants_are_roughly_balanced() -> None:
    counts = Counter(assign(str(uuid.UUID(int=i)), EXPERIMENT).variant for i in range(4000))
    assert set(counts) == {"control", "treatment"}
    for value in counts.values():
        assert 1600 < value < 2400, counts


def test_buckets_stay_in_range() -> None:
    for i in range(500):
        key = assignment_key(str(uuid.UUID(int=i)), "any")
        assert 0 <= bucket_of(key) < HASH_BUCKETS


def test_a_malformed_experiment_is_rejected_at_construction() -> None:
    with pytest.raises(ExperimentError, match="2\\+ variants"):
        Experiment("bad", ("only",))
    with pytest.raises(ExperimentError, match="duplicate"):
        Experiment("bad", ("a", "a"))


def test_unknown_experiment_fails_loudly() -> None:
    with pytest.raises(ExperimentError, match="unknown experiment"):
        get_experiment("does_not_exist")


def test_the_registry_only_holds_valid_experiments() -> None:
    assert REGISTRY
    for experiment_id, experiment in REGISTRY.items():
        assert experiment.experiment_id == experiment_id
        assert len(experiment.variants) >= 2


def test_assignments_persist_and_are_idempotent(settings: object) -> None:
    from app.persistence.database import Database
    from app.persistence.repositories import GuestRepository

    database = Database(settings)  # type: ignore[arg-type]
    guest_id = uuid.uuid4()
    result: Assignment = assign(str(guest_id), get_experiment("reason_phrasing_v1"))

    with database.session() as session:
        guests = GuestRepository(session)
        guests.touch(guest_id)
        first = guests.assignment(guest_id, result)
        second = guests.assignment(guest_id, result)
        assert first.id == second.id
        assert len(guests.assignments(guest_id)) == 1
        assert first.variant == result.variant
        assert first.assignment_key == result.assignment_key
    database.dispose()
