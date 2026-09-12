"""Audio route policy — SDD section 5.3.

One rule carries the weight here: when headphones disconnect and audio would
fall back to the device speaker, playback is interrupted rather than continued.
Suddenly broadcasting a meditation to a room is a privacy event, not a
convenience, and the person wearing the headphones is usually not the only one
who finds out.

Everything else about a route change is recorded and ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.playback.state_machine import RunCommand


class AudioRoute(StrEnum):
    """Where sound is coming out. Coarse on purpose - the distinction that
    matters is private versus audible to the room."""

    SPEAKER = "speaker"
    RECEIVER = "receiver"
    """The earpiece. Private, but not a route anyone chooses for a session."""
    HEADPHONES = "headphones"
    BLUETOOTH = "bluetooth"
    CAR = "car"
    AIRPLAY = "airplay"
    UNKNOWN = "unknown"


PRIVATE_ROUTES = frozenset({AudioRoute.HEADPHONES, AudioRoute.BLUETOOTH, AudioRoute.RECEIVER})


def is_private(route: AudioRoute) -> bool:
    """Whether only the listener hears it.

    UNKNOWN is treated as audible to the room. Guessing wrong in that direction
    pauses a session; guessing wrong the other way broadcasts one.
    """
    return route in PRIVATE_ROUTES


@dataclass(frozen=True, slots=True)
class RouteDecision:
    command: RunCommand | None
    """The command to apply, or None to continue playing."""
    event_type: str
    reason: str

    @property
    def interrupts(self) -> bool:
        return self.command is RunCommand.INTERRUPT


def on_route_change(previous: AudioRoute, current: AudioRoute) -> RouteDecision:
    """What a route change means for playback."""
    if previous == current:
        return RouteDecision(None, "route_changed", "no change")

    if is_private(previous) and not is_private(current):
        return RouteDecision(
            RunCommand.INTERRUPT,
            "playback_interrupted",
            f"{previous.value} lost; {current.value} would be audible to the room",
        )

    return RouteDecision(None, "route_changed", f"{previous.value} to {current.value}")


def on_focus_lost() -> RouteDecision:
    """A phone call, an alarm, another app taking audio."""
    return RouteDecision(RunCommand.INTERRUPT, "playback_interrupted", "audio focus lost")


def on_focus_regained() -> RouteDecision:
    """Focus coming back leaves the run paused.

    The user decides when to start meditating again. Resuming for them means a
    voice starts talking the moment a call ends, which is exactly wrong.
    """
    return RouteDecision(
        RunCommand.INTERRUPTION_ENDED, "playback_focus_regained", "audio focus regained"
    )
