"""Audio cache policy — SDD section 9.2 and 9.4.

The cache is content-addressed, shared across guests on a device, and holds
nothing personal: every entry is product-authored guidance identical for every
user. Two consequences the SDD calls out explicitly, both decisions rather than
oversights: the cache is not encrypted, because encrypting it would imply a
confidentiality property that does not exist; and guest deletion does not clear
it, because there is no guest data in it to delete.

This module is the policy, not the storage. It decides what to evict, what to
refuse, and which rung of the fallback chain a segment lands on. The bytes live
on the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SOFT_CAP_BYTES = 150 * 1024 * 1024
STALE_AFTER_DAYS = 90


class ResolutionRung(StrEnum):
    """Where a segment's audio came from — SDD section 9.4, in order."""

    CACHED = "cached"
    FETCHED = "fetched"
    DEVICE_TTS = "device_tts"
    TEXT_ONLY = "text_only"
    """Transcript on screen, held for min_ms. The rung that keeps a session
    usable for someone whose TTS engine is broken, or who is deaf."""


@dataclass(frozen=True, slots=True)
class CacheEntry:
    render_key: str
    byte_size: int
    duration_ms: int
    content_sha256: str
    last_hit_age_days: int
    pinned: bool
    """Belongs to a run that is ready or playing. Never evicted."""

    def __post_init__(self) -> None:
        if self.byte_size < 0:
            raise ValueError(f"{self.render_key}: negative size")


@dataclass(frozen=True, slots=True)
class EvictionPlan:
    evict: tuple[str, ...]
    retained_bytes: int
    over_cap: bool
    """True when the cap still cannot be met without evicting a pinned entry."""


def plan_eviction(entries: list[CacheEntry], cap_bytes: int = SOFT_CAP_BYTES) -> EvictionPlan:
    """Choose what to drop, oldest-unused first.

    Stale entries go first regardless of pressure - ninety days without a hit
    means the corpus moved on. After that it is least-recently-used, and a
    pinned entry is never evicted: dropping audio out from under a session that
    is about to play it trades a little disk for a broken meditation.
    """
    evict: list[str] = []
    keep: list[CacheEntry] = []

    for entry in entries:
        if entry.pinned:
            keep.append(entry)
        elif entry.last_hit_age_days >= STALE_AFTER_DAYS:
            evict.append(entry.render_key)
        else:
            keep.append(entry)

    keep.sort(key=lambda e: (e.pinned, -e.last_hit_age_days))
    total = sum(e.byte_size for e in keep)
    retained: list[CacheEntry] = list(keep)

    for entry in keep:
        if total <= cap_bytes:
            break
        if entry.pinned:
            continue
        evict.append(entry.render_key)
        retained.remove(entry)
        total -= entry.byte_size

    return EvictionPlan(evict=tuple(evict), retained_bytes=total, over_cap=total > cap_bytes)


def verify(entry: CacheEntry, observed_sha256: str) -> bool:
    """Whether a cached file may be played.

    A mismatch is not a warning to log and play anyway. The entry is deleted and
    re-fetched, because playing unverified bytes is how a corrupt file becomes a
    sound nobody intended in the middle of a meditation.
    """
    return entry.content_sha256 == observed_sha256


@dataclass(frozen=True, slots=True)
class ResolutionAttempt:
    cached: bool
    cache_valid: bool
    fetchable: bool
    device_tts_available: bool


def resolve(attempt: ResolutionAttempt) -> ResolutionRung:
    """Walk the fallback chain — SDD 9.4. Never returns silent failure."""
    if attempt.cached and attempt.cache_valid:
        return ResolutionRung.CACHED
    if attempt.fetchable:
        return ResolutionRung.FETCHED
    if attempt.device_tts_available:
        return ResolutionRung.DEVICE_TTS
    return ResolutionRung.TEXT_ONLY


def guest_deletion_clears_cache() -> bool:
    """No — and it is written down so it stays a decision.

    The cache holds product-authored guidance, identical for every user. There
    is no guest data in it, so clearing it on deletion would delete nothing
    personal while making the next session slower for everyone on the device.
    """
    return False
