"""SessionPlan v2 — recommendation intent plus frozen content to a typed timeline.

Deterministic by contract:

    same recommendation intent
  + same definition version
  + same planner version
  = same canonical plan
  = same plan_hash

Pure. No I/O, no clock, no randomness. The existing Program001 stage allocator
does the second-level arithmetic; this layer subdivides each stage into the
speech, silence and bell segments a person actually experiences.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from string import Template
from typing import Any

from app.domain.practice.models import Protocol
from app.domain.recommendation.engine import Recommendation
from app.domain.session.planner import allocate_stage_seconds
from app.domain.state.models import StateVector
from app.domain.timeline.definition import MIN_SILENCE_FRACTION, SessionDefinition
from app.domain.timeline.segments import (
    BellId,
    BellSegment,
    MarkerSegment,
    SilenceSegment,
    SpeechSegment,
    Timeline,
    content_hash,
)

PLANNER_VERSION = "1"
PLAN_SCHEMA_VERSION = 1

# Bells frame the session. Fixed, short, and never elastic.
OPENING_BELL_MS = 2_000
CLOSING_BELL_MS = 2_000

# Speech estimate before anything has been measured. Deliberately conservative:
# under-estimating speech is what forces silence to absorb, and absorbing is
# cheaper than extending.
WORDS_PER_MINUTE = 130
MIN_SPEECH_MS = 2_000


def estimate_speech_ms(text: str, words_per_minute: int = WORDS_PER_MINUTE) -> int:
    """A planning estimate, not a promise.

    Real duration depends on the voice, the engine and the rate, none of which
    is knowable here. The timing model treats this as a budget and reconciles
    against measured durations later.
    """
    words = len([w for w in text.split() if w])
    return max(MIN_SPEECH_MS, round(words / words_per_minute * 60_000))


@dataclass(frozen=True, slots=True)
class SessionPlanV2:
    """A frozen, executable plan."""

    schema_version: int
    planner_version: int | str
    definition_id: str
    practice_id: str
    protocol_id: str
    public_title: str
    locale: str
    target_total_ms: int
    guidance_density: float
    timeline: Timeline

    @property
    def plan_hash(self) -> str:
        return content_hash(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "planner_version": str(self.planner_version),
            "definition_id": self.definition_id,
            "practice_id": self.practice_id,
            "protocol_id": self.protocol_id,
            "public_title": self.public_title,
            "locale": self.locale,
            "target_total_ms": self.target_total_ms,
            "guidance_density": self.guidance_density,
            "segments": self.timeline.as_list(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionPlanV2:
        """Rebuild a stored plan, so a past session stays executable and readable."""
        return cls(
            schema_version=int(data["schema_version"]),
            planner_version=data["planner_version"],
            definition_id=data["definition_id"],
            practice_id=data["practice_id"],
            protocol_id=data["protocol_id"],
            public_title=data["public_title"],
            locale=data["locale"],
            target_total_ms=int(data["target_total_ms"]),
            guidance_density=float(data["guidance_density"]),
            timeline=Timeline.from_list(data["segments"]),
        )

    def transcript(self) -> tuple[str, ...]:
        """The whole session as text. Silent mode and accessibility depend on it."""
        return tuple(s.transcript for s in self.timeline.speech())


def render_key_for(
    text: str,
    locale: str,
    voice_id: str,
    style: str,
    provider_id: str,
    provider_version: str,
    render_version: str,
) -> str:
    """Content-addressed audio key — SDD ADR-004-04.

    Derived from render inputs only. Never from guest identity: two people who
    hear the same sentence share one cache entry, which is both a storage win
    and the reason the cache reveals content rather than who asked for it.

    Fields are separated by a NUL byte so two different splits cannot hash
    identically, and text is NFC-normalised first: the same visible sentence
    authored with decomposed accents must not miss the cache.
    """
    fields = (
        normalize_text(text),
        locale,
        voice_id,
        style,
        provider_id,
        provider_version,
        render_version,
    )
    return hashlib.sha256(b"\x00".join(f.encode("utf-8") for f in fields)).hexdigest()


def normalize_text(text: str) -> str:
    """NFC, collapse internal whitespace, strip the ends — SDD section 9.1."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# The placeholder render identity used at plan time. The runtime substitutes the
# provider it actually has; the key is recomputed then, which is why the plan
# stores the inputs rather than pretending to know the provider.
PLAN_TIME_VOICE = "default"
PLAN_TIME_STYLE = "calm"
PLAN_TIME_PROVIDER = "unbound"
PLAN_TIME_PROVIDER_VERSION = "0"
RENDER_CONTRACT_VERSION = "1"


def build_plan(
    recommendation: Recommendation,
    definition: SessionDefinition,
    protocol: Protocol,
    state: StateVector | None = None,
) -> SessionPlanV2:
    """Expand a recommendation into a typed timeline.

    Stage seconds come from the Program001 allocator, so adaptation and the
    sum-to-duration invariant are inherited rather than reimplemented. Within a
    stage the split is: speech first, then its silence.
    """
    total_seconds = recommendation.duration_minutes * 60
    allocations = allocate_stage_seconds(protocol, total_seconds, state)

    segments: list[Any] = [
        BellSegment(
            id="bell_open",
            bell_id=BellId.OPENING,
            duration_ms=OPENING_BELL_MS,
            asset_key="bell.opening",
        )
    ]

    for index, (stage, seconds) in enumerate(zip(definition.stages, allocations, strict=True)):
        stage_ms = seconds * 1000
        text = Template(stage.prompt_template).safe_substitute(
            duration_minutes=recommendation.duration_minutes,
            stage_minutes=max(1, round(seconds / 60)),
            practice_title=definition.public_title,
        )
        text = " ".join(text.split())

        speech_ms = min(estimate_speech_ms(text), max(MIN_SPEECH_MS, stage_ms // 2))
        silence_ms = max(0, stage_ms - speech_ms)

        segments.append(
            SpeechSegment(
                id=f"speech_{index}_{stage.stage_id}",
                text=text,
                transcript=text,
                estimated_ms=speech_ms,
                render_key=render_key_for(
                    text,
                    definition.locale,
                    PLAN_TIME_VOICE,
                    PLAN_TIME_STYLE,
                    PLAN_TIME_PROVIDER,
                    PLAN_TIME_PROVIDER_VERSION,
                    RENDER_CONTRACT_VERSION,
                ),
            )
        )

        if silence_ms > 0:
            # The floor is proportional to the silence actually allocated, not to
            # the definition's nominal tail. Using the nominal value let a
            # ten-minute session shrink to 84 seconds, which is not a shorter
            # meditation - it is a different thing entirely. Silence is the
            # practice, so most of it is not negotiable.
            floor_ms = max(
                min(stage.min_silence_seconds * 1000, silence_ms),
                int(silence_ms * MIN_SILENCE_FRACTION),
            )
            segments.append(
                SilenceSegment(
                    id=f"silence_{index}_{stage.stage_id}",
                    target_ms=silence_ms,
                    min_ms=floor_ms,
                    elastic=True,
                )
            )

        # A silent anchor after each stage, so an experiment or an analytic can
        # name this moment without it having to be audible.
        segments.append(
            MarkerSegment(id=f"marker_{index}_{stage.stage_id}", marker_id=stage.stage_id)
        )

    segments.append(
        BellSegment(
            id="bell_close",
            bell_id=BellId.CLOSING,
            duration_ms=CLOSING_BELL_MS,
            asset_key="bell.closing",
        )
    )

    timeline = Timeline(segments=tuple(segments))
    return SessionPlanV2(
        schema_version=PLAN_SCHEMA_VERSION,
        planner_version=PLANNER_VERSION,
        definition_id=definition.definition_id,
        practice_id=recommendation.practice_id,
        protocol_id=definition.protocol_id,
        public_title=definition.public_title,
        locale=definition.locale,
        target_total_ms=timeline.nominal_total_ms,
        guidance_density=recommendation.guidance_density,
        timeline=timeline,
    )
