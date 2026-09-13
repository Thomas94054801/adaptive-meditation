"""Segment scheduling — which segment a position lands in, and what comes next.

Pure arithmetic over a plan's offsets. Both the player and process recovery ask
the same questions, so they ask them of the same code: a resume that disagreed
with playback about where minute four is would be a bug nobody could see.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.timeline.planner_v2 import SessionPlanV2
from app.domain.timeline.segments import Segment, SpeechSegment


@dataclass(frozen=True, slots=True)
class ScheduledSegment:
    index: int
    segment: Segment
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def offset_into(self, position_ms: int) -> int:
        """How far into this segment a position is. Clamped to the segment."""
        return max(0, min(position_ms, self.end_ms) - self.start_ms)


def schedule(plan: SessionPlanV2) -> tuple[ScheduledSegment, ...]:
    """The plan as absolute [start, end) windows."""
    offsets = plan.timeline.offsets_ms()
    segments = plan.timeline.segments
    return tuple(
        ScheduledSegment(
            index=index,
            segment=segment,
            start_ms=start,
            end_ms=start + segment.nominal_ms,
        )
        for index, (segment, start) in enumerate(zip(segments, offsets, strict=True))
    )


def segment_at(plan: SessionPlanV2, position_ms: int) -> ScheduledSegment | None:
    """The segment containing this position, or None past the end.

    Half-open windows, so a boundary belongs to the segment starting there and
    a position cannot be in two segments at once.
    """
    if position_ms < 0:
        return None
    for scheduled in schedule(plan):
        if scheduled.start_ms <= position_ms < scheduled.end_ms:
            return scheduled
    return None


def next_segment(plan: SessionPlanV2, position_ms: int) -> ScheduledSegment | None:
    """The first segment beginning at or after this position."""
    for scheduled in schedule(plan):
        if scheduled.start_ms >= position_ms:
            return scheduled
    return None


def resume_position(plan: SessionPlanV2, position_ms: int) -> int:
    """Where playback restarts after an interruption at this position.

    Inside speech, the segment restarts from its beginning: repeating up to one
    sentence beats joining one halfway through. Inside silence or a bell, the
    position stands - resuming silence mid-way is not jarring, and rewinding it
    would quietly lengthen the session.
    """
    scheduled = segment_at(plan, position_ms)
    if scheduled is None:
        return max(0, min(position_ms, plan.timeline.nominal_total_ms))
    if isinstance(scheduled.segment, SpeechSegment):
        return scheduled.start_ms
    return position_ms


def remaining_ms(plan: SessionPlanV2, position_ms: int) -> int:
    return max(0, plan.timeline.nominal_total_ms - max(0, position_ms))


def progress_fraction(plan: SessionPlanV2, position_ms: int) -> float:
    """0.0 to 1.0. What a progress bar shows, and what completion_ratio uses."""
    total = plan.timeline.nominal_total_ms
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, position_ms / total))
