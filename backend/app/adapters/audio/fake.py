"""A deterministic renderer, for tests and for local development.

Deterministic because a test that asserts a plan's timing must not depend on a
speech engine's mood. The same request always produces the same duration and the
same content hash, so a cache test can assert a hit without a real file existing.

It is not a stand-in for voice quality. Nothing here says anything about how a
human voice sounds, and no automated test can.
"""

from __future__ import annotations

import hashlib

from app.domain.audio.render import RenderRequest, RenderResult, RenderUnavailable

PROVIDER_ID = "fake"
PROVIDER_VERSION = "1"

# Deliberately different from the planner's estimate, so a test exercising the
# elastic-silence path sees a real overrun rather than a perfect fit.
MS_PER_CHARACTER = 62


class FakeSpeechRenderer:
    """Renders anything, produces no audio, always agrees with itself."""

    provider_id = PROVIDER_ID
    provider_version = PROVIDER_VERSION

    def __init__(self, supported_locales: tuple[str, ...] = ("en-US",)) -> None:
        self._locales = supported_locales
        self.calls: list[RenderRequest] = []

    def supports(self, locale: str, voice_id: str) -> bool:
        return locale in self._locales and bool(voice_id)

    def render(self, request: RenderRequest) -> RenderResult:
        if not self.supports(request.locale, request.voice_id):
            raise RenderUnavailable(f"{PROVIDER_ID} cannot speak {request.locale}")

        self.calls.append(request)
        payload = request.render_key.encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        characters = len(request.as_dict()["text"])
        return RenderResult(
            render_key=request.render_key,
            duration_ms=max(1, characters * MS_PER_CHARACTER),
            content_sha256=digest,
            uri=f"fake://{request.render_key}",
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            byte_size=characters * 1024,
        )
