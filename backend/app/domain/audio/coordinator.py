"""Render coordination — SDD section 9.1b.

Turns a plan into a render manifest: one entry per speech segment, giving the
client the key, where to fetch it, how long it is and the hash to verify. The
coordinator asks the cache first and a renderer only on a miss, which is what
makes synthesis a build-time cost rather than a per-session one.

Three time domains stay separate here: synthesis at plan time, fetching at
prepare time, playback touching neither. That separation is what makes the
offline contract true rather than aspirational.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.audio.render import (
    RenderRequest,
    RenderResult,
    RenderUnavailable,
    SpeechRenderer,
)
from app.domain.timeline.planner_v2 import SessionPlanV2

# Lookup returns a previously measured render, or None.
CacheLookup = Callable[[str], RenderResult | None]


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    segment_id: str
    render_key: str
    duration_ms: int
    content_sha256: str
    uri: str
    from_cache: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "render_key": self.render_key,
            "duration_ms": self.duration_ms,
            "content_sha256": self.content_sha256,
            "uri": self.uri,
        }


@dataclass(frozen=True, slots=True)
class RenderManifest:
    entries: tuple[ManifestEntry, ...]
    unresolved: tuple[str, ...]
    """Segment ids no renderer could produce. They fall to the text-only rung
    rather than failing the session."""

    @property
    def complete(self) -> bool:
        return not self.unresolved

    @property
    def cache_hits(self) -> int:
        return len([e for e in self.entries if e.from_cache])

    def as_dict(self) -> dict[str, object]:
        return {
            "entries": [entry.as_dict() for entry in self.entries],
            "unresolved": list(self.unresolved),
        }

    def measured_durations(self) -> dict[str, int]:
        """Segment id to measured duration, for the planner to use next time."""
        return {entry.segment_id: entry.duration_ms for entry in self.entries}


def build_manifest(
    plan: SessionPlanV2,
    renderer: SpeechRenderer,
    lookup: CacheLookup,
    *,
    voice_id: str = "default",
    style: str = "calm",
) -> RenderManifest:
    """Resolve every speech segment, preferring the cache.

    A segment no renderer can produce is recorded as unresolved rather than
    raising: the session still plays, with the transcript on screen for that
    segment. Failing the whole meditation because one sentence would not
    synthesise is the wrong trade.
    """
    entries: list[ManifestEntry] = []
    unresolved: list[str] = []

    for segment in plan.timeline.speech():
        request = RenderRequest(
            text=segment.text,
            locale=plan.locale,
            voice_id=voice_id,
            style=style,
            provider_id=renderer.provider_id,
            provider_version=renderer.provider_version,
        )

        cached = lookup(request.render_key)
        if cached is not None:
            entries.append(_entry(segment.id, cached, from_cache=True))
            continue

        try:
            rendered = renderer.render(request)
        except RenderUnavailable:
            unresolved.append(segment.id)
            continue
        entries.append(_entry(segment.id, rendered, from_cache=False))

    return RenderManifest(entries=tuple(entries), unresolved=tuple(unresolved))


def _entry(segment_id: str, result: RenderResult, *, from_cache: bool) -> ManifestEntry:
    return ManifestEntry(
        segment_id=segment_id,
        render_key=result.render_key,
        duration_ms=result.duration_ms,
        content_sha256=result.content_sha256,
        uri=result.uri,
        from_cache=from_cache,
    )
