"""The speech rendering port — SDD sections 8.4, 8.5 and 9.

A render request carries product-authored text and the voice identity to speak
it with. It carries nothing about who is listening, and that is enforced here
rather than left to reviewer diligence: :func:`assert_no_personal_data` runs over
the serialised request, and a test drives it with a guest id, a session id and an
experiment arm to prove each one is refused.

The port is deliberately narrow. Everything behind it - device-native TTS today,
server pre-generated audio next - answers the same question: given this text and
this voice, produce audio, its measured duration, and the hash of its bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.timeline.planner_v2 import normalize_text, render_key_for

# Field names a request must never carry. Checked against the serialised form,
# so a nested dict cannot smuggle one through.
PROHIBITED_FIELDS = frozenset(
    {
        "guest_id",
        "user_id",
        "session_id",
        "check_in_id",
        "device_id",
        "experiment_arm",
        "experiment_id",
        "variant",
        "assignment_key",
        "history",
        "notes",
        "journal",
        "feedback",
        "ip",
        "email",
    }
)

# A UUID anywhere in a request is a guest, a session or a device, none of which
# belong in a synthesis request.
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


class PersonalDataInRenderRequest(ValueError):
    """A render request that would have told a provider who is listening."""


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """What a renderer is asked for. Product-authored text only."""

    text: str
    locale: str
    voice_id: str
    style: str
    provider_id: str
    provider_version: str
    render_version: str = "1"

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("render request has no text")
        assert_no_personal_data(self.as_dict())

    @property
    def render_key(self) -> str:
        return render_key_for(
            self.text,
            self.locale,
            self.voice_id,
            self.style,
            self.provider_id,
            self.provider_version,
            self.render_version,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": normalize_text(self.text),
            "locale": self.locale,
            "voice_id": self.voice_id,
            "style": self.style,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "render_version": self.render_version,
        }


def assert_no_personal_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Refuse a request that would identify the listener.

    Checks keys and values, at any depth. The value check is what catches a
    guest id pasted into a text field, which is the way this actually happens.
    """
    _walk(payload)
    return payload


def _walk(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in PROHIBITED_FIELDS:
                raise PersonalDataInRenderRequest(
                    f"render request carries {key!r} at {path or 'root'}"
                )
            _walk(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _walk(item, f"{path}[{index}]")
    elif isinstance(value, str) and _UUID.search(value):
        raise PersonalDataInRenderRequest(
            f"render request carries what looks like an identifier at {path or 'root'}"
        )


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Audio produced for one request.

    ``content_sha256`` is the hash of the bytes, not of the request: it is what
    a client verifies on read, so a corrupt cache entry is deleted rather than
    played.
    """

    render_key: str
    duration_ms: int
    content_sha256: str
    uri: str
    provider_id: str
    provider_version: str
    byte_size: int

    def __post_init__(self) -> None:
        if self.duration_ms <= 0:
            raise ValueError(f"{self.render_key}: duration must be positive")
        if len(self.content_sha256) != 64:
            raise ValueError(f"{self.render_key}: content_sha256 must be a sha256 hex digest")

    def as_dict(self) -> dict[str, Any]:
        return {
            "render_key": self.render_key,
            "duration_ms": self.duration_ms,
            "content_sha256": self.content_sha256,
            "uri": self.uri,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "byte_size": self.byte_size,
        }


class RenderUnavailable(Exception):
    """This renderer cannot produce this request. The next rung is tried."""


class SpeechRenderer(Protocol):
    """The port. Everything that can speak implements exactly this."""

    provider_id: str
    provider_version: str

    def supports(self, locale: str, voice_id: str) -> bool:
        """Whether this renderer can speak this locale in this voice."""
        ...

    def render(self, request: RenderRequest) -> RenderResult:
        """Produce audio, or raise :class:`RenderUnavailable`."""
        ...
