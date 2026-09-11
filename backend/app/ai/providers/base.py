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
    """What a provider is allowed to see. The envelope fields are read-only."""

    practice_id: str
    duration_minutes: int
    guidance_density: float
    stage_prompts: tuple[str, ...]


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
