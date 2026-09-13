"""Typed meditation timeline segments — SDD ADR-004-01.

A meditation is an ordered list of things that happen, not one long utterance.
Speech, silence and a bell are different kinds of event with different failure
modes, different durations and different meaning to the person sitting there, so
they are different types.

Everything here is frozen and hashable: a plan is content-addressed, and a type
that could be mutated after hashing would make the hash a lie.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class SegmentKind(StrEnum):
    SPEECH = "speech"
    SILENCE = "silence"
    BELL = "bell"
    MARKER = "marker"


class BellId(StrEnum):
    """The bells the product actually uses.

    Closed set rather than a free string: a bell is an audio asset with
    provenance, and an unbounded identifier would let a plan reference one that
    does not exist.
    """

    OPENING = "opening"
    CLOSING = "closing"
    TRANSITION = "transition"


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """Spoken guidance.

    ``estimated_ms`` is what the planner budgeted. The real duration is not
    knowable until it is spoken - device voices differ by OS version, engine and
    rate - which is why silence is elastic and why this is an estimate rather
    than a promise.
    """

    id: str
    text: str
    transcript: str
    estimated_ms: int
    render_key: str
    kind: Literal[SegmentKind.SPEECH] = SegmentKind.SPEECH

    def __post_init__(self) -> None:
        if self.estimated_ms <= 0:
            raise ValueError(f"speech {self.id}: estimated_ms must be positive")
        if not self.text.strip():
            raise ValueError(f"speech {self.id}: empty text")
        if not self.transcript.strip():
            # Every spoken segment carries a textual form. A segment without one
            # could not be shown in silent mode, and silent mode is how a user
            # who cannot hear completes a session.
            raise ValueError(f"speech {self.id}: empty transcript")

    @property
    def nominal_ms(self) -> int:
        return self.estimated_ms


@dataclass(frozen=True, slots=True)
class SilenceSegment:
    """Intentional silence.

    ``target_ms`` is the intended length and ``min_ms`` the floor below which it
    stops being silence and becomes a gap. Elastic silences absorb speech
    overrun; inelastic ones do not move at all.
    """

    id: str
    target_ms: int
    min_ms: int
    elastic: bool = True
    kind: Literal[SegmentKind.SILENCE] = SegmentKind.SILENCE

    def __post_init__(self) -> None:
        if self.target_ms <= 0:
            raise ValueError(f"silence {self.id}: target_ms must be positive")
        if self.min_ms < 0:
            raise ValueError(f"silence {self.id}: min_ms cannot be negative")
        if self.min_ms > self.target_ms:
            raise ValueError(f"silence {self.id}: min_ms exceeds target_ms")

    @property
    def nominal_ms(self) -> int:
        return self.target_ms

    @property
    def shrinkable_ms(self) -> int:
        """How much this silence can give up before hitting its floor."""
        return self.target_ms - self.min_ms if self.elastic else 0


@dataclass(frozen=True, slots=True)
class BellSegment:
    """A bell or cue. Fixed duration - a bell that stretches is not a bell."""

    id: str
    bell_id: BellId
    duration_ms: int
    asset_key: str
    kind: Literal[SegmentKind.BELL] = SegmentKind.BELL

    def __post_init__(self) -> None:
        if self.duration_ms <= 0:
            raise ValueError(f"bell {self.id}: duration_ms must be positive")

    @property
    def nominal_ms(self) -> int:
        return self.duration_ms


@dataclass(frozen=True, slots=True)
class MarkerSegment:
    """A silent, zero-duration anchor.

    Exists so an experiment or an analytic can name a moment in the timeline
    without that moment having to be audible.
    """

    id: str
    marker_id: str
    kind: Literal[SegmentKind.MARKER] = SegmentKind.MARKER

    @property
    def nominal_ms(self) -> int:
        return 0


Segment = SpeechSegment | SilenceSegment | BellSegment | MarkerSegment


def segment_as_dict(segment: Segment) -> dict[str, Any]:
    """Canonical serialisation. Key order is fixed so the hash is stable."""
    match segment:
        case SpeechSegment():
            return {
                "kind": SegmentKind.SPEECH.value,
                "id": segment.id,
                "text": segment.text,
                "transcript": segment.transcript,
                "estimated_ms": segment.estimated_ms,
                "render_key": segment.render_key,
            }
        case SilenceSegment():
            return {
                "kind": SegmentKind.SILENCE.value,
                "id": segment.id,
                "target_ms": segment.target_ms,
                "min_ms": segment.min_ms,
                "elastic": segment.elastic,
            }
        case BellSegment():
            return {
                "kind": SegmentKind.BELL.value,
                "id": segment.id,
                "bell_id": segment.bell_id.value,
                "duration_ms": segment.duration_ms,
                "asset_key": segment.asset_key,
            }
        case MarkerSegment():
            return {
                "kind": SegmentKind.MARKER.value,
                "id": segment.id,
                "marker_id": segment.marker_id,
            }


def segment_from_dict(data: dict[str, Any]) -> Segment:
    """Rebuild a segment from its canonical form.

    Needed for replay: a session stored last March must still be readable.
    """
    kind = data["kind"]
    match kind:
        case SegmentKind.SPEECH.value:
            return SpeechSegment(
                id=data["id"],
                text=data["text"],
                transcript=data["transcript"],
                estimated_ms=int(data["estimated_ms"]),
                render_key=data["render_key"],
            )
        case SegmentKind.SILENCE.value:
            return SilenceSegment(
                id=data["id"],
                target_ms=int(data["target_ms"]),
                min_ms=int(data["min_ms"]),
                elastic=bool(data["elastic"]),
            )
        case SegmentKind.BELL.value:
            return BellSegment(
                id=data["id"],
                bell_id=BellId(data["bell_id"]),
                duration_ms=int(data["duration_ms"]),
                asset_key=data["asset_key"],
            )
        case SegmentKind.MARKER.value:
            return MarkerSegment(id=data["id"], marker_id=data["marker_id"])
        case _:
            raise ValueError(f"unknown segment kind {kind!r}")


def canonical_json(payload: Any) -> str:
    """Stable serialisation for hashing. Sorted keys, no incidental whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Timeline:
    """An ordered, contiguous list of segments."""

    segments: tuple[Segment, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("a timeline needs at least one segment")
        ids = [s.id for s in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate segment id in timeline")

    @property
    def nominal_total_ms(self) -> int:
        return sum(s.nominal_ms for s in self.segments)

    @property
    def shrinkable_ms(self) -> int:
        """Total slack available to absorb speech overrun."""
        return sum(s.shrinkable_ms for s in self.segments if isinstance(s, SilenceSegment))

    @property
    def minimum_total_ms(self) -> int:
        """The shortest this session can be without cutting guidance."""
        return self.nominal_total_ms - self.shrinkable_ms

    def offsets_ms(self) -> tuple[int, ...]:
        """Planned start offset of each segment."""
        offsets: list[int] = []
        running = 0
        for segment in self.segments:
            offsets.append(running)
            running += segment.nominal_ms
        return tuple(offsets)

    def speech(self) -> tuple[SpeechSegment, ...]:
        return tuple(s for s in self.segments if isinstance(s, SpeechSegment))

    def as_list(self) -> list[dict[str, Any]]:
        return [segment_as_dict(s) for s in self.segments]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> Timeline:
        return cls(segments=tuple(segment_from_dict(item) for item in data))
