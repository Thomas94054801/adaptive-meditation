"""Playback time — SDD section 5.3, "elapsed is playback time, not wall time".

A session paused at minute three and resumed the next morning is still at minute
three. Wall time is the wrong clock for every question the runtime asks, and
using it is how "this session lasted three hours" gets written to a journal.

Nothing here reads a clock. The caller supplies monotonic readings, which is
what makes this testable and what keeps a device whose wall clock jumps - a
timezone change, an NTP correction, a user setting the date - from moving a
meditation's position.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# A device's monotonic clock and our accumulated position will not agree
# exactly; audio hardware, scheduler jitter and decode latency all contribute.
# Past this, the two have diverged enough that something is actually wrong.
DRIFT_TOLERANCE_MS = 1_000


class ClockError(ValueError):
    """A reading that cannot be true, such as monotonic time going backwards."""


@dataclass(frozen=True, slots=True)
class PlaybackClock:
    """Accumulated playback position, excluding every paused interval.

    ``running_since_ms`` is the monotonic reading at which the current playing
    interval began, or None while paused. ``accumulated_ms`` is everything
    banked before that interval.
    """

    accumulated_ms: int = 0
    running_since_ms: int | None = None

    @property
    def is_running(self) -> bool:
        return self.running_since_ms is not None

    def elapsed_ms(self, now_ms: int) -> int:
        """Position at this monotonic reading."""
        if self.running_since_ms is None:
            return self.accumulated_ms
        if now_ms < self.running_since_ms:
            raise ClockError(f"monotonic time went backwards: {now_ms} < {self.running_since_ms}")
        return self.accumulated_ms + (now_ms - self.running_since_ms)

    def start(self, now_ms: int) -> PlaybackClock:
        """Begin or resume. Starting an already-running clock changes nothing.

        Idempotent on purpose: a duplicate resume from a retrying client must
        not bank the interval twice.
        """
        if self.running_since_ms is not None:
            return self
        return replace(self, running_since_ms=now_ms)

    def pause(self, now_ms: int) -> PlaybackClock:
        """Bank the current interval. Pausing a paused clock changes nothing."""
        if self.running_since_ms is None:
            return self
        return PlaybackClock(accumulated_ms=self.elapsed_ms(now_ms), running_since_ms=None)

    def seek(self, position_ms: int) -> PlaybackClock:
        """Move to a position, keeping the running/paused state.

        Used by recovery, which restarts a speech segment from its beginning.
        """
        if position_ms < 0:
            raise ClockError(f"negative position: {position_ms}")
        return PlaybackClock(accumulated_ms=position_ms, running_since_ms=self.running_since_ms)


@dataclass(frozen=True, slots=True)
class DriftReading:
    expected_ms: int
    """Where the timeline says playback should be."""
    observed_ms: int
    """Where the audio engine reports it is."""

    @property
    def drift_ms(self) -> int:
        return self.observed_ms - self.expected_ms

    @property
    def exceeded(self) -> bool:
        return abs(self.drift_ms) > DRIFT_TOLERANCE_MS


def measure_drift(expected_ms: int, observed_ms: int) -> DriftReading:
    """Compare the timeline's position against the audio engine's.

    Reported rather than corrected: silently seeking to hide drift makes the
    symptom invisible while the cause keeps working, and a meditation that
    jumps is worse than one that is a second off.
    """
    return DriftReading(expected_ms=expected_ms, observed_ms=observed_ms)
