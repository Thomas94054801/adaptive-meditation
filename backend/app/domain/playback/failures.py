"""Failure taxonomy — SDD section 21.

The shape of this table is the point: almost nothing is fatal. The only two
fatal classes are an invalid plan, which is a bug on our side, and an unexpected
runtime fault. Everything a user is actually likely to meet — no signal, a full
disk, another app holding audio focus — degrades to something that still plays.

Encoding the matrix as data rather than as branches means the runtime cannot
quietly decide that a recoverable failure ends the session.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureCode(StrEnum):
    CONTENT_PLAN_INVALID = "CONTENT_PLAN_INVALID"
    AUDIO_ASSET_MISSING = "AUDIO_ASSET_MISSING"
    RENDER_UNAVAILABLE = "RENDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    CACHE_CORRUPTION = "CACHE_CORRUPTION"
    UNSUPPORTED_CODEC = "UNSUPPORTED_CODEC"
    AUDIO_FOCUS_DENIED = "AUDIO_FOCUS_DENIED"
    PLAYBACK_RUNTIME_ERROR = "PLAYBACK_RUNTIME_ERROR"
    STORAGE_EXHAUSTED = "STORAGE_EXHAUSTED"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    """What the runtime is allowed to do about one failure."""

    retryable: bool
    recoverable: bool
    user_actionable: bool
    fatal: bool
    recovery: str
    """How it degrades. Empty when it does not."""


# Section 21, verbatim. A test compares this against the table.
FAILURE_POLICY: dict[FailureCode, FailurePolicy] = {
    FailureCode.CONTENT_PLAN_INVALID: FailurePolicy(
        retryable=False, recoverable=False, user_actionable=False, fatal=True, recovery=""
    ),
    FailureCode.AUDIO_ASSET_MISSING: FailurePolicy(
        retryable=True,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="per-segment fallback",
    ),
    FailureCode.RENDER_UNAVAILABLE: FailurePolicy(
        retryable=True,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="silent mode",
    ),
    FailureCode.PROVIDER_TIMEOUT: FailurePolicy(
        retryable=True,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="retry with backoff",
    ),
    FailureCode.PROVIDER_REJECTED: FailurePolicy(
        retryable=False,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="fallback renderer",
    ),
    FailureCode.CACHE_CORRUPTION: FailurePolicy(
        retryable=True,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="delete and re-render",
    ),
    FailureCode.UNSUPPORTED_CODEC: FailurePolicy(
        retryable=False,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="alternate asset or device TTS",
    ),
    FailureCode.AUDIO_FOCUS_DENIED: FailurePolicy(
        retryable=True,
        recoverable=True,
        user_actionable=True,
        fatal=False,
        recovery="ask the user to stop other audio",
    ),
    FailureCode.PLAYBACK_RUNTIME_ERROR: FailurePolicy(
        retryable=False,
        recoverable=True,
        user_actionable=False,
        fatal=True,
        recovery="recover() into ready",
    ),
    FailureCode.STORAGE_EXHAUSTED: FailurePolicy(
        retryable=False,
        recoverable=True,
        user_actionable=True,
        fatal=False,
        recovery="stream or device TTS",
    ),
    FailureCode.NETWORK_UNAVAILABLE: FailurePolicy(
        retryable=True,
        recoverable=True,
        user_actionable=False,
        fatal=False,
        recovery="device TTS",
    ),
}


def policy_for(code: FailureCode) -> FailurePolicy:
    return FAILURE_POLICY[code]


def is_fatal(code: FailureCode) -> bool:
    """Fatal to the attempt. Only two codes qualify, and both are our bug."""
    return FAILURE_POLICY[code].fatal


def degrades_to_playable(code: FailureCode) -> bool:
    """Whether the user still gets a session. Everything non-fatal must."""
    return FAILURE_POLICY[code].recoverable
