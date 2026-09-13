"""Playback state machine — SDD section 5.

Two decisions here are product decisions wearing technical clothes, and both are
enforced rather than documented:

``backgrounded`` is not a state. Audio that stops when the screen locks is not a
meditation app, so backgrounding is an environment event recorded in the
journal. Modelling it as a playback state would imply playback stops.

``interrupted`` resolves to ``paused``, never straight back to ``playing``.
Audio resuming by itself after a phone call - possibly on a speaker, in a room
with other people - is a worse failure than a session that waits for a tap.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunState(StrEnum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FAILED = "failed"


class RunCommand(StrEnum):
    PREPARE = "prepare"
    RESOLVED = "resolved"
    UNRESOLVABLE = "unresolvable"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    INTERRUPT = "interrupt"
    INTERRUPTION_ENDED = "interruption_ended"
    COMPLETE = "complete"
    ABANDON = "abandon"
    FAIL = "fail"
    RECOVER = "recover"


TERMINAL_STATES: frozenset[RunState] = frozenset({RunState.COMPLETED, RunState.ABANDONED})

# The whole contract in one table. Anything absent is impossible by construction
# rather than by a forgotten branch.
TRANSITIONS: dict[tuple[RunState, RunCommand], RunState] = {
    (RunState.CREATED, RunCommand.PREPARE): RunState.PREPARING,
    (RunState.CREATED, RunCommand.ABANDON): RunState.ABANDONED,
    (RunState.PREPARING, RunCommand.RESOLVED): RunState.READY,
    (RunState.PREPARING, RunCommand.UNRESOLVABLE): RunState.FAILED,
    (RunState.PREPARING, RunCommand.ABANDON): RunState.ABANDONED,
    (RunState.READY, RunCommand.START): RunState.PLAYING,
    (RunState.READY, RunCommand.ABANDON): RunState.ABANDONED,
    (RunState.READY, RunCommand.FAIL): RunState.FAILED,
    (RunState.PLAYING, RunCommand.PAUSE): RunState.PAUSED,
    # An interruption is not a pause the user asked for, so it has its own
    # command and lands in paused only once the interruption ends.
    (RunState.PLAYING, RunCommand.INTERRUPT): RunState.PAUSED,
    (RunState.PLAYING, RunCommand.COMPLETE): RunState.COMPLETED,
    (RunState.PLAYING, RunCommand.ABANDON): RunState.ABANDONED,
    (RunState.PLAYING, RunCommand.FAIL): RunState.FAILED,
    (RunState.PAUSED, RunCommand.RESUME): RunState.PLAYING,
    (RunState.PAUSED, RunCommand.ABANDON): RunState.ABANDONED,
    (RunState.PAUSED, RunCommand.FAIL): RunState.FAILED,
    # An interruption arriving while already paused changes nothing, and its end
    # must not start playback.
    (RunState.PAUSED, RunCommand.INTERRUPT): RunState.PAUSED,
    (RunState.PAUSED, RunCommand.INTERRUPTION_ENDED): RunState.PAUSED,
    (RunState.FAILED, RunCommand.RECOVER): RunState.READY,
    (RunState.FAILED, RunCommand.ABANDON): RunState.ABANDONED,
}


class InvalidTransition(ValueError):
    """Raised when a command cannot be applied in the current state."""

    def __init__(self, state: RunState, command: RunCommand) -> None:
        super().__init__(f"cannot apply {command.value!r} while {state.value!r}")
        self.state = state
        self.command = command


@dataclass(frozen=True, slots=True)
class TransitionResult:
    previous: RunState
    current: RunState
    command: RunCommand

    @property
    def changed(self) -> bool:
        return self.previous is not self.current


def is_terminal(state: RunState) -> bool:
    return state in TERMINAL_STATES


def can_apply(state: RunState, command: RunCommand) -> bool:
    return (state, command) in TRANSITIONS


def apply(state: RunState, command: RunCommand) -> TransitionResult:
    """Apply a command, or refuse.

    Terminal states accept nothing. A second ``complete`` on a completed run is
    handled by the idempotency layer above this, which returns the existing
    state rather than reaching here - a client retrying after a flaky network is
    doing the right thing and should not be punished for it.
    """
    if is_terminal(state):
        raise InvalidTransition(state, command)
    try:
        return TransitionResult(state, TRANSITIONS[(state, command)], command)
    except KeyError:
        raise InvalidTransition(state, command) from None


def reachable_states() -> frozenset[RunState]:
    """Every state reachable from CREATED. Guards against an orphaned state."""
    seen = {RunState.CREATED}
    frontier = [RunState.CREATED]
    while frontier:
        state = frontier.pop()
        for (origin, _), destination in TRANSITIONS.items():
            if origin is state and destination not in seen:
                seen.add(destination)
                frontier.append(destination)
    return frozenset(seen)
