"""AI and TTS provider boundaries.

AI is presentation intelligence. The deterministic engine owns practice family,
duration, guidance density and safety constraints; a provider may only restate
the wording of an already-selected protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PersonalizationRequest:
    """What a provider is allowed to see. The envelope fields are read-only.

    Program005 adds the presentation variant already chosen for this session
    ("canonical" or "returning"), so a provider rewrites in that register. It
    is the only non-envelope fact here: no guest id, session id, check-in
    values, history, experiment arm, feedback or free text ever join it, and
    ``FORBIDDEN_REQUEST_FIELDS`` is checked against the serialised request.
    """

    practice_id: str
    duration_minutes: int
    guidance_density: float
    stage_prompts: tuple[str, ...]
    presentation_variant: str = "canonical"


# Names that must never appear in a serialised personalization request.
FORBIDDEN_REQUEST_FIELDS: frozenset[str] = frozenset(
    {
        "guest_id",
        "session_id",
        "check_in_id",
        "user_id",
        "stress",
        "energy",
        "mental_activity",
        "sleepiness",
        "history",
        "experiment",
        "variant_assignment",
        "feedback",
        "notes",
        "outcome_score",
        "device_id",
    }
)


@dataclass(frozen=True, slots=True)
class PersonalizationResult:
    """What a provider may return: wording, and its own claim about the envelope."""

    provider_id: str
    practice_id: str
    duration_minutes: int
    guidance_density: float
    stage_prompts: tuple[str, ...]


@runtime_checkable
class AIProvider(Protocol):
    provider_id: str

    def personalize(self, request: PersonalizationRequest) -> PersonalizationResult: ...


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    text: str
    voice_id: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechResult:
    provider_id: str
    audio: bytes | None
    mime_type: str | None


@runtime_checkable
class TTSProvider(Protocol):
    provider_id: str

    def synthesize(self, request: SpeechRequest) -> SpeechResult: ...
