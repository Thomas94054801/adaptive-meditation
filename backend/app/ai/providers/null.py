"""No-op providers used whenever no credential is configured, including tests."""

from __future__ import annotations

from app.ai.providers.base import (
    PersonalizationRequest,
    PersonalizationResult,
    SpeechRequest,
    SpeechResult,
)


class NullAIProvider:
    """Returns the deterministic wording unchanged."""

    provider_id = "null"

    def personalize(self, request: PersonalizationRequest) -> PersonalizationResult:
        return PersonalizationResult(
            provider_id=self.provider_id,
            practice_id=request.practice_id,
            duration_minutes=request.duration_minutes,
            guidance_density=request.guidance_density,
            stage_prompts=request.stage_prompts,
        )


class NullTTSProvider:
    """Produces no audio. The Program001 client renders text, not speech."""

    provider_id = "null"

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        return SpeechResult(provider_id=self.provider_id, audio=None, mime_type=None)
