"""Resolved playback timelines — SDD A2.

A `SessionPlanV2` says what was intended. A resolution says what the device
actually had: measured audio durations, the hash of each produced file, and the
silence allocation that follows from them. The plan is content-addressed by
`plan_hash`; a resolution is content-addressed by `resolution_hash`, and the two
are separate because they answer different questions and change at different
times.

The device computes the resolution and reaches `ready` on its own. This module
is what lets the server **recompute the same hash from the same inputs** and
reject a resolution that does not describe the plan it claims to. Without an
independent recomputation, a resolution is just a number the client asserted.

Canonicalisation is spelled out rather than delegated to a JSON encoder, because
two languages agreeing on "some JSON" is not a contract. Field order is fixed,
separators are explicit, text is NFC, and every duration is an integer
millisecond — no floats anywhere, since float formatting is exactly where two
runtimes diverge.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.timeline.planner_v2 import SessionPlanV2
from app.domain.timeline.segments import SilenceSegment, SpeechSegment
from app.domain.timeline.timing import TimingOutcome, resolve_timing

CANONICALIZATION_VERSION = "1"
TIMING_POLICY_VERSION = "1"

# Unit and record separators. Chosen because they cannot occur in a segment id,
# a hash or a decimal integer, so no escaping scheme is needed - and an escaping
# scheme is one more thing two languages can implement differently.
_UNIT = "\x1f"
_RECORD = "\x1e"

# A measured duration this far from the plan's estimate means something is
# wrong with the measurement, not with the estimate.
MAX_PLAUSIBLE_SEGMENT_MS = 30 * 60 * 1000


class MeasurementSource(StrEnum):
    """Where a duration came from. Never inferred."""

    DEVICE_REPORTED = "device_reported"
    """Measured by decoding the produced file on the device."""

    PLAN_ESTIMATE = "plan_estimate"
    """No audio; the planner's estimate stands. Silent mode uses this."""


class ResolutionInvalid(ValueError):
    """A resolution that does not describe the plan it references."""


@dataclass(frozen=True, slots=True)
class ResolvedSegment:
    """One segment as it will actually play."""

    segment_id: str
    kind: str
    effective_ms: int
    audio_sha256: str | None = None
    """The output fingerprint. None for silence and for silent mode."""

    def __post_init__(self) -> None:
        if self.effective_ms < 0:
            raise ResolutionInvalid(f"{self.segment_id}: negative duration")
        if self.effective_ms > MAX_PLAUSIBLE_SEGMENT_MS:
            raise ResolutionInvalid(
                f"{self.segment_id}: {self.effective_ms}ms exceeds the plausible maximum"
            )
        if self.audio_sha256 is not None and len(self.audio_sha256) != 64:
            raise ResolutionInvalid(f"{self.segment_id}: audio_sha256 must be a sha256 digest")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "segment_id": self.segment_id,
            "kind": self.kind,
            "effective_ms": self.effective_ms,
        }
        # Nulls are omitted rather than serialised, so the two languages cannot
        # disagree about whether absent and null hash the same.
        if self.audio_sha256 is not None:
            payload["audio_sha256"] = self.audio_sha256
        return payload


@dataclass(frozen=True, slots=True)
class ResolvedTimeline:
    """What the device will play, and what it measured to get there."""

    plan_hash: str
    locale: str
    revision: int
    timing_policy_version: str
    canonicalization_version: str
    measurement_source: MeasurementSource
    audio_mode: str
    segments: tuple[ResolvedSegment, ...]
    extended_by_ms: int
    absorbed_ms: int
    outcome: str

    @property
    def total_ms(self) -> int:
        return sum(segment.effective_ms for segment in self.segments)

    def canonical(self) -> str:
        """The exact string both languages hash. Order and separators are fixed."""
        head = _UNIT.join(
            (
                self.canonicalization_version,
                _nfc(self.plan_hash),
                _nfc(self.locale),
                str(self.revision),
                _nfc(self.timing_policy_version),
                _nfc(self.measurement_source.value),
                _nfc(self.audio_mode),
            )
        )
        body = "".join(
            _UNIT.join(
                (
                    _nfc(segment.segment_id),
                    _nfc(segment.kind),
                    str(segment.effective_ms),
                    segment.audio_sha256 or "",
                )
            )
            + _RECORD
            for segment in self.segments
        )
        tail = _UNIT.join(
            (str(self.total_ms), str(self.extended_by_ms), str(self.absorbed_ms), self.outcome)
        )
        return f"{head}{_RECORD}{body}{tail}"

    @property
    def resolution_hash(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonicalization_version": self.canonicalization_version,
            "plan_hash": self.plan_hash,
            "locale": self.locale,
            "revision": self.revision,
            "timing_policy_version": self.timing_policy_version,
            "measurement_source": self.measurement_source.value,
            "audio_mode": self.audio_mode,
            "segments": [segment.as_dict() for segment in self.segments],
            "total_ms": self.total_ms,
            "extended_by_ms": self.extended_by_ms,
            "absorbed_ms": self.absorbed_ms,
            "outcome": self.outcome,
            "resolution_hash": self.resolution_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolvedTimeline:
        return cls(
            plan_hash=str(data["plan_hash"]),
            locale=str(data["locale"]),
            revision=int(data["revision"]),
            timing_policy_version=str(data["timing_policy_version"]),
            canonicalization_version=str(data["canonicalization_version"]),
            measurement_source=MeasurementSource(data["measurement_source"]),
            audio_mode=str(data["audio_mode"]),
            segments=tuple(
                ResolvedSegment(
                    segment_id=str(s["segment_id"]),
                    kind=str(s["kind"]),
                    effective_ms=int(s["effective_ms"]),
                    audio_sha256=s.get("audio_sha256"),
                )
                for s in data["segments"]
            ),
            extended_by_ms=int(data["extended_by_ms"]),
            absorbed_ms=int(data["absorbed_ms"]),
            outcome=str(data["outcome"]),
        )


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def resolve_for(
    plan: SessionPlanV2,
    measured_speech_ms: dict[str, int],
    *,
    audio_mode: str = "audible",
    revision: int = 1,
    measurement_source: MeasurementSource = MeasurementSource.DEVICE_REPORTED,
    audio_hashes: dict[str, str] | None = None,
) -> ResolvedTimeline:
    """Build a resolution from a plan and the durations actually measured.

    This is the function that finally gives ``resolve_timing`` a caller. The
    silence allocation is not recomputed by hand here: it comes from the same
    arithmetic the unit tests pin, so the resolution cannot drift from the
    timing policy it names.
    """
    resolution = resolve_timing(plan.timeline, measured_speech_ms)
    allocated = {a.segment_id: a.allocated_ms for a in resolution.allocations}
    hashes = audio_hashes or {}

    segments: list[ResolvedSegment] = []
    for segment in plan.timeline.segments:
        if isinstance(segment, SilenceSegment):
            effective = allocated.get(segment.id, segment.target_ms)
        elif isinstance(segment, SpeechSegment):
            effective = measured_speech_ms.get(segment.id, segment.estimated_ms)
        else:
            effective = segment.nominal_ms
        segments.append(
            ResolvedSegment(
                segment_id=segment.id,
                kind=segment.kind.value,
                effective_ms=effective,
                audio_sha256=hashes.get(segment.id),
            )
        )

    return ResolvedTimeline(
        plan_hash=plan.plan_hash,
        locale=plan.locale,
        revision=revision,
        timing_policy_version=TIMING_POLICY_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=measurement_source,
        audio_mode=audio_mode,
        segments=tuple(segments),
        extended_by_ms=resolution.extended_by_ms,
        absorbed_ms=resolution.absorbed_ms,
        outcome=resolution.outcome.value,
    )


def validate_against_plan(resolution: ResolvedTimeline, plan: SessionPlanV2) -> None:
    """Check a client-supplied resolution against the frozen plan.

    Content validation, not a sign check. Everything here is something a
    tampered or buggy client could get wrong while still producing
    non-negative numbers: the wrong plan, a missing or invented segment, a
    reordered timeline, a silence below its floor, or a total that does not add
    up to its own parts.
    """
    if resolution.plan_hash != plan.plan_hash:
        raise ResolutionInvalid("resolution references a different plan")
    if resolution.canonicalization_version != CANONICALIZATION_VERSION:
        raise ResolutionInvalid(
            f"unsupported canonicalization_version {resolution.canonicalization_version!r}"
        )
    if resolution.timing_policy_version != TIMING_POLICY_VERSION:
        raise ResolutionInvalid(
            f"unsupported timing_policy_version {resolution.timing_policy_version!r}"
        )
    if resolution.revision < 1:
        raise ResolutionInvalid("revision must be positive")
    if resolution.audio_mode not in {"audible", "silent_by_choice", "silent_degraded"}:
        raise ResolutionInvalid(f"unknown audio_mode {resolution.audio_mode!r}")

    planned = list(plan.timeline.segments)
    if len(resolution.segments) != len(planned):
        raise ResolutionInvalid(
            f"resolution has {len(resolution.segments)} segments, plan has {len(planned)}"
        )

    floors = {s.id: s.min_ms for s in planned if isinstance(s, SilenceSegment)}
    for index, (resolved, expected) in enumerate(zip(resolution.segments, planned, strict=True)):
        # Order matters, not just membership: a reordered timeline is a
        # different session, and set comparison would accept it.
        if resolved.segment_id != expected.id:
            raise ResolutionInvalid(
                f"segment {index} is {resolved.segment_id!r}, plan says {expected.id!r}"
            )
        if resolved.kind != expected.kind.value:
            raise ResolutionInvalid(
                f"{resolved.segment_id}: kind {resolved.kind!r} does not match the plan"
            )
        floor = floors.get(resolved.segment_id)
        if floor is not None and resolved.effective_ms < floor:
            raise ResolutionInvalid(
                f"{resolved.segment_id}: {resolved.effective_ms}ms is below its " f"{floor}ms floor"
            )
        if resolved.kind == "marker" and resolved.effective_ms != 0:
            raise ResolutionInvalid(f"{resolved.segment_id}: a marker has no duration")

    if resolution.extended_by_ms < 0 or resolution.absorbed_ms < 0:
        raise ResolutionInvalid("extension and absorption cannot be negative")
    if resolution.outcome not in {o.value for o in TimingOutcome}:
        raise ResolutionInvalid(f"unknown timing outcome {resolution.outcome!r}")

    if resolution.audio_mode == "audible":
        missing = [
            s.segment_id
            for s in resolution.segments
            if s.kind in {"speech", "bell"} and not s.audio_sha256
        ]
        if missing:
            raise ResolutionInvalid(
                "an audible resolution needs an audio hash for every speech and "
                f"bell segment; missing: {missing}"
            )


def recompute_hash(resolution: ResolvedTimeline) -> str:
    """Independently recompute the hash the client sent.

    A resolution whose stated hash does not match its own content is rejected;
    accepting the client's number would make the field decoration.
    """
    return resolution.resolution_hash
