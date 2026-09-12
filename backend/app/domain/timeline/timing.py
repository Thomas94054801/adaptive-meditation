"""Speech-overrun feasibility accounting.

The SDD's first instinct — "elastic silence absorbs the variance" — is only true
while there is slack left. This module does the arithmetic honestly, including
the case where there is not.

The rule, in order of priority:

1. never create negative silence;
2. preserve spoken guidance — never truncate someone mid-sentence to satisfy a
   timer;
3. preserve the minimum intentional-silence floors, because silence below its
   floor stops being silence and becomes an awkward gap;
4. if 1-3 cannot be met inside the target duration, **extend the session** and
   record that it was extended.

A meditation that runs eleven seconds long is a meditation. One that cuts the
closing guidance off halfway through a word is a bug the user experiences as the
app breaking at the worst possible moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.timeline.segments import SilenceSegment, Timeline


class TimingOutcome(StrEnum):
    """How the plan resolved against its target duration."""

    ON_TARGET = "on_target"
    """Speech ran to estimate, or under. Silences keep their targets."""

    ABSORBED = "absorbed"
    """Overrun fitted inside the elastic slack. Target duration preserved."""

    ABSORBED_AT_FLOOR = "absorbed_at_floor"
    """Overrun consumed the slack exactly. Every elastic silence is at its floor."""

    DURATION_EXTENDED = "duration_extended"
    """Overrun exceeded the slack. Guidance and floors kept; the session is longer."""


@dataclass(frozen=True, slots=True)
class SilenceAllocation:
    segment_id: str
    target_ms: int
    min_ms: int
    allocated_ms: int

    def __post_init__(self) -> None:
        if self.allocated_ms < 0:
            raise ValueError(f"{self.segment_id}: negative silence ({self.allocated_ms}ms)")
        if self.allocated_ms < self.min_ms:
            raise ValueError(
                f"{self.segment_id}: {self.allocated_ms}ms is below the " f"{self.min_ms}ms floor"
            )


@dataclass(frozen=True, slots=True)
class TimingResolution:
    """The arithmetic, kept as evidence rather than folded into a duration."""

    outcome: TimingOutcome
    target_total_ms: int
    actual_total_ms: int
    speech_overrun_ms: int
    available_shrinkable_ms: int
    absorbed_ms: int
    extended_by_ms: int
    allocations: tuple[SilenceAllocation, ...]

    @property
    def was_extended(self) -> bool:
        return self.extended_by_ms > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "target_total_ms": self.target_total_ms,
            "actual_total_ms": self.actual_total_ms,
            "speech_overrun_ms": self.speech_overrun_ms,
            "available_shrinkable_ms": self.available_shrinkable_ms,
            "absorbed_ms": self.absorbed_ms,
            "extended_by_ms": self.extended_by_ms,
            "allocations": [
                {
                    "segment_id": a.segment_id,
                    "target_ms": a.target_ms,
                    "min_ms": a.min_ms,
                    "allocated_ms": a.allocated_ms,
                }
                for a in self.allocations
            ],
        }


def resolve_timing(
    timeline: Timeline, actual_speech_ms: dict[str, int] | None = None
) -> TimingResolution:
    """Fit measured speech durations into the timeline's silence budget.

    ``actual_speech_ms`` maps speech segment id to its measured duration. A
    segment absent from the map is assumed to have run to estimate, which is what
    happens before anything has been spoken.
    """
    measured = actual_speech_ms or {}
    target_total = timeline.nominal_total_ms

    overrun = sum(
        max(0, measured.get(s.id, s.estimated_ms) - s.estimated_ms) for s in timeline.speech()
    )
    underrun = sum(
        max(0, s.estimated_ms - measured.get(s.id, s.estimated_ms)) for s in timeline.speech()
    )
    # Speech that finishes early gives time back, so the net is what silence has
    # to deal with. It cannot go below zero: a short session is not padded out by
    # stretching silence beyond its target, because the target is the intent.
    net_overrun = max(0, overrun - underrun)

    silences = [s for s in timeline.segments if isinstance(s, SilenceSegment)]
    available = sum(s.shrinkable_ms for s in silences)
    absorbed = min(net_overrun, available)
    extended_by = net_overrun - absorbed

    allocations = tuple(_allocate(silences, absorbed))

    actual_total = (
        target_total
        + sum(measured.get(s.id, s.estimated_ms) - s.estimated_ms for s in timeline.speech())
        - sum(a.target_ms - a.allocated_ms for a in allocations)
    )

    if net_overrun == 0:
        outcome = TimingOutcome.ON_TARGET
    elif extended_by > 0:
        outcome = TimingOutcome.DURATION_EXTENDED
    elif absorbed == available:
        outcome = TimingOutcome.ABSORBED_AT_FLOOR
    else:
        outcome = TimingOutcome.ABSORBED

    return TimingResolution(
        outcome=outcome,
        target_total_ms=target_total,
        actual_total_ms=max(timeline.minimum_total_ms, actual_total),
        speech_overrun_ms=net_overrun,
        available_shrinkable_ms=available,
        absorbed_ms=absorbed,
        extended_by_ms=extended_by,
        allocations=allocations,
    )


def _allocate(silences: list[SilenceSegment], to_absorb: int) -> list[SilenceAllocation]:
    """Take ``to_absorb`` ms out of the silences, proportionally, never below floor.

    Integer arithmetic with a deterministic remainder pass, so the same inputs
    always produce the same allocation on every machine.
    """
    allocations = [SilenceAllocation(s.id, s.target_ms, s.min_ms, s.target_ms) for s in silences]
    if to_absorb <= 0:
        return allocations

    capacity = sum(s.shrinkable_ms for s in silences)
    if capacity <= 0:
        return allocations

    taken: dict[str, int] = {}
    running = 0
    for index, silence in enumerate(silences):
        if index == len(silences) - 1:
            # The last one takes the rounding remainder, so the total is exact.
            share = to_absorb - running
        else:
            share = to_absorb * silence.shrinkable_ms // capacity
        share = min(share, silence.shrinkable_ms)
        taken[silence.id] = share
        running += share

    # A capped share can leave a shortfall; spread it over whatever still has room.
    shortfall = to_absorb - sum(taken.values())
    for silence in silences:
        if shortfall <= 0:
            break
        room = silence.shrinkable_ms - taken[silence.id]
        extra = min(room, shortfall)
        taken[silence.id] += extra
        shortfall -= extra

    return [
        SilenceAllocation(s.id, s.target_ms, s.min_ms, s.target_ms - taken.get(s.id, 0))
        for s in silences
    ]
