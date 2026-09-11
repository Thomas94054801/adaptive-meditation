"""Deterministic session plan rendering.

Turns (protocol, duration, guidance density) into an exact second-by-second
stage timeline. Same inputs, same plan - the allocation uses exact rational
arithmetic and a fixed tie-break, so there is no float drift and no dependence
on dict ordering.

Memory: one plan per session request, at most a handful of stages. Nothing here
accumulates across requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from string import Template

from app.domain.practice.models import Protocol

# Guidance cue spacing. Density 0.0 is the sparsest allowed spacing, 1.0 the
# densest; the renderer interpolates linearly between them.
SPARSE_CUE_INTERVAL_SECONDS = 90
DENSE_CUE_INTERVAL_SECONDS = 20


class ProtocolRenderError(ValueError):
    """Raised when a protocol cannot render the requested duration or density."""


@dataclass(frozen=True, slots=True)
class RenderedStage:
    """One stage of an executable session timeline."""

    id: str
    intent: str
    prompt: str
    start_offset_seconds: int
    duration_seconds: int
    guidance_cue_count: int
    silence_after_seconds: int


@dataclass(frozen=True, slots=True)
class SessionPlan:
    """A fully rendered, client-executable session."""

    protocol_id: str
    protocol_version: int
    practice_id: str
    public_title: str
    total_seconds: int
    guidance_density: float
    stages: tuple[RenderedStage, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "practice_id": self.practice_id,
            "public_title": self.public_title,
            "total_seconds": self.total_seconds,
            "guidance_density": self.guidance_density,
            "stages": [
                {
                    "id": stage.id,
                    "intent": stage.intent,
                    "prompt": stage.prompt,
                    "start_offset_seconds": stage.start_offset_seconds,
                    "duration_seconds": stage.duration_seconds,
                    "guidance_cue_count": stage.guidance_cue_count,
                    "silence_after_seconds": stage.silence_after_seconds,
                }
                for stage in self.stages
            ],
        }


def _round_half_up(value: Decimal | Fraction | float | int) -> int:
    """Round half away from zero.

    Python's built-in ``round`` is half-to-even, which would make 44.5 and 45.5
    round in opposite directions - fine statistically, surprising in a contract
    that has to be reproducible by a Dart client.
    """
    if isinstance(value, Fraction):
        exact = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        exact = Decimal(str(value))
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def allocate_stage_seconds(protocol: Protocol, total_seconds: int) -> tuple[int, ...]:
    """Split ``total_seconds`` across stages, respecting each stage's bounds.

    Every stage gets its minimum first; the remainder is shared in proportion to
    each stage's flexibility (``max - min``) using exact fractions and a
    largest-remainder tie-break resolved by stage order. The result always sums
    to ``total_seconds`` exactly.
    """
    minimums = [stage.min_seconds for stage in protocol.stages]
    flexibility = [stage.max_seconds - stage.min_seconds for stage in protocol.stages]
    floor_total = sum(minimums)
    ceiling_total = sum(stage.max_seconds for stage in protocol.stages)

    if total_seconds < floor_total or total_seconds > ceiling_total:
        raise ProtocolRenderError(
            f"protocol {protocol.id!r} renders {floor_total}-{ceiling_total}s, "
            f"asked for {total_seconds}s"
        )

    remaining = total_seconds - floor_total
    flex_total = sum(flexibility)
    if remaining == 0:
        return tuple(minimums)
    if flex_total == 0:  # pragma: no cover - excluded by the bounds check above
        raise ProtocolRenderError(f"protocol {protocol.id!r} has no flexible seconds to allocate")

    exact = [Fraction(remaining * flex, flex_total) for flex in flexibility]
    base = [int(value) for value in exact]
    leftover = remaining - sum(base)
    # Largest fractional remainder wins; ties go to the earlier stage.
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - base[i]), i))
    for index in order[:leftover]:
        base[index] += 1

    return tuple(minimum + extra for minimum, extra in zip(minimums, base, strict=True))


def cue_interval_seconds(guidance_density: float) -> int:
    """Seconds between spoken cues at a given density. Denser means more cues."""
    span = SPARSE_CUE_INTERVAL_SECONDS - DENSE_CUE_INTERVAL_SECONDS
    return SPARSE_CUE_INTERVAL_SECONDS - _round_half_up(Decimal(str(guidance_density)) * span)


def render_plan(
    protocol: Protocol,
    *,
    duration_minutes: int,
    guidance_density: float,
    practice_public_title: str | None = None,
) -> SessionPlan:
    """Render the executable timeline for one session."""
    if duration_minutes not in protocol.duration_supported:
        raise ProtocolRenderError(
            f"protocol {protocol.id!r} does not declare {duration_minutes} minutes"
        )
    if not protocol.accepts_density(guidance_density):
        raise ProtocolRenderError(
            f"guidance density {guidance_density} outside protocol range "
            f"{protocol.guidance_density_range}"
        )

    total_seconds = duration_minutes * 60
    allocations = allocate_stage_seconds(protocol, total_seconds)
    interval = cue_interval_seconds(guidance_density)
    title = practice_public_title or protocol.public_title

    stages: list[RenderedStage] = []
    offset = 0
    for stage, seconds in zip(protocol.stages, allocations, strict=True):
        # Silence never eats more than a third of the stage, so a short session
        # is still guided rather than mostly silent.
        silence = min(stage.silence_after_seconds, seconds // 3)
        guided_seconds = seconds - silence
        cue_count = max(1, _round_half_up(Fraction(guided_seconds, interval)))
        stages.append(
            RenderedStage(
                id=stage.id,
                intent=stage.intent,
                prompt=Template(stage.prompt_template).safe_substitute(
                    duration_minutes=duration_minutes,
                    stage_minutes=max(1, _round_half_up(Fraction(seconds, 60))),
                    practice_title=title,
                ),
                start_offset_seconds=offset,
                duration_seconds=seconds,
                guidance_cue_count=cue_count,
                silence_after_seconds=silence,
            )
        )
        offset += seconds

    return SessionPlan(
        protocol_id=protocol.id,
        protocol_version=protocol.version,
        practice_id=protocol.practice_id,
        public_title=title,
        total_seconds=total_seconds,
        guidance_density=guidance_density,
        stages=tuple(stages),
    )
