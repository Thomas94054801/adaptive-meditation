"""Provider selection.

Resolution is explicit and fails loudly on an unknown name rather than falling
back to a silent default, but an absent credential is not an error: it selects
the null provider, and the deterministic core is unaffected.
"""

from __future__ import annotations

from app.ai.providers.base import AIProvider, TTSProvider
from app.ai.providers.null import NullAIProvider, NullTTSProvider
from app.ai.safety.router import NoopSafetyRouter, SafetyRouter
from app.settings import Settings


class UnknownProviderError(ValueError):
    """Raised when settings name a provider that is not implemented."""


def build_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "null" or not settings.ai_api_key:
        return NullAIProvider()
    raise UnknownProviderError(
        f"AI provider {settings.ai_provider!r} is not implemented in Program001"
    )


def build_tts_provider(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "null":
        return NullTTSProvider()
    raise UnknownProviderError(
        f"TTS provider {settings.tts_provider!r} is not implemented in Program001"
    )


def build_safety_router(settings: Settings) -> SafetyRouter:
    return NoopSafetyRouter()
