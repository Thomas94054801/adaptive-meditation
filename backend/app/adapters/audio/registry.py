"""Choosing a speech renderer from configuration.

The default is none, and that is the shipping configuration: the first provider
is device-native TTS, which runs on the client, so the backend resolves nothing
and every segment falls to the device. A server-side renderer is the second
adapter, and it plugs in here without the coordinator or the planner changing.

The fake renderer is refused in production. It is the same class of mistake as a
test schema in a production database, and it gets the same treatment: a
configuration that could quietly ship silence is rejected at startup rather than
discovered by a user.
"""

from __future__ import annotations

from app.adapters.audio.fake import FakeSpeechRenderer
from app.domain.audio.render import RenderRequest, RenderResult, RenderUnavailable, SpeechRenderer


class NullSpeechRenderer:
    """Resolves nothing, on purpose.

    Not a failure mode. With device-native TTS as the shipped provider, the
    backend having no audio to offer is the expected case, and the client's
    fallback chain takes it from there.
    """

    provider_id = "none"
    provider_version = "0"

    def supports(self, locale: str, voice_id: str) -> bool:
        return False

    def render(self, request: RenderRequest) -> RenderResult:
        raise RenderUnavailable("no server-side renderer is configured")


class UnknownSpeechProvider(ValueError):
    """A configured provider nobody implements."""


def build_renderer(provider: str, *, app_env: str) -> SpeechRenderer:
    """Build the configured renderer, refusing combinations that cannot be right."""
    normalized = (provider or "none").strip().lower()

    if normalized in {"", "none", "null"}:
        return NullSpeechRenderer()

    if normalized == "fake":
        if app_env == "production":
            raise UnknownSpeechProvider(
                "the fake renderer produces no audio and must never be selected " "in production"
            )
        return FakeSpeechRenderer()

    raise UnknownSpeechProvider(f"unknown speech provider {provider!r}")
