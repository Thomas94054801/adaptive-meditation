"""Session-plan assembly and playback command application.

Sits between the API and the pure domain: it owns the ordering of "freeze the
content, build the plan, persist it" and the idempotency rules for commands, so
neither the route handler nor the state machine has to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.playback.state_machine import (
    InvalidTransition,
    RunCommand,
    RunState,
    apply,
    is_terminal,
)
from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import Recommendation
from app.domain.state.models import StateVector
from app.domain.timeline.definition import SessionDefinition, definition_for
from app.domain.timeline.planner_v2 import SessionPlanV2, build_plan
from app.domain.timeline.segments import segment_as_dict


@dataclass(frozen=True, slots=True)
class PlannedSession:
    definition: SessionDefinition
    plan: SessionPlanV2


def plan_session(
    catalog: KnowledgeCatalog,
    recommendation: Recommendation,
    state: StateVector | None = None,
    locale: str = "en-US",
) -> PlannedSession:
    """Freeze the content, then plan against the frozen copy.

    The order matters: planning from the live knowledge files would leave the
    session describing whatever the files say later, which is the reproducibility
    hole this program closes.
    """
    definition = definition_for(catalog, recommendation.practice_id, locale=locale)
    protocol = catalog.protocol_for(recommendation.practice_id)
    plan = build_plan(recommendation, definition, protocol, state)
    return PlannedSession(definition=definition, plan=plan)


def plan_personalized_session(
    catalog: KnowledgeCatalog,
    recommendation: Recommendation,
    definition: SessionDefinition,
    state: StateVector | None = None,
) -> PlannedSession:
    """Plan against a definition that was already chosen and frozen.

    Program005 picks the definition (canonical or returning wording) before
    planning; the planner itself is the same one ``plan_session`` uses, so a
    personalized session is planned exactly like any other.
    """
    protocol = catalog.protocol_for(recommendation.practice_id)
    plan = build_plan(recommendation, definition, protocol, state)
    return PlannedSession(definition=definition, plan=plan)


def plan_response_payload(plan: SessionPlanV2) -> dict[str, Any]:
    """Wire form. Includes the derived timing bounds the client needs to schedule."""
    return {
        "schema_version": plan.schema_version,
        "planner_version": str(plan.planner_version),
        "definition_id": plan.definition_id,
        "plan_hash": plan.plan_hash,
        "practice_id": plan.practice_id,
        "protocol_id": plan.protocol_id,
        "public_title": plan.public_title,
        "locale": plan.locale,
        "target_total_ms": plan.target_total_ms,
        "minimum_total_ms": plan.timeline.minimum_total_ms,
        "shrinkable_ms": plan.timeline.shrinkable_ms,
        "guidance_density": plan.guidance_density,
        "segments": [segment_as_dict(s) for s in plan.timeline.segments],
    }


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    state: RunState
    applied: bool
    elapsed_ms: int
    last_segment_id: str | None
    sequence: int


class StaleCommand(Exception):
    """A command that arrived after a later one. Dropped, not an error."""


def apply_command(
    *,
    current_state: str | None,
    current_sequence: int,
    current_elapsed_ms: int,
    current_segment_id: str | None,
    command: str,
    sequence: int,
    elapsed_ms: int,
    segment_id: str | None,
) -> CommandOutcome:
    """Apply a playback command with idempotency and ordering rules.

    Three cases that are not errors:

    - a **replayed** sequence: the client retried after a dropped response;
    - an **out-of-order** sequence: rapid taps arriving shuffled;
    - a command on a **terminal** run: a second ``complete`` after a flaky
      network is the client doing the right thing.

    All three return the existing state with ``applied=False`` rather than
    raising, because punishing a correct retry is how duplicate completions get
    written.
    """
    state = RunState(current_state or RunState.CREATED.value)

    if sequence <= current_sequence and current_sequence > 0:
        return CommandOutcome(
            state, False, current_elapsed_ms, current_segment_id, current_sequence
        )

    if is_terminal(state):
        return CommandOutcome(
            state, False, current_elapsed_ms, current_segment_id, current_sequence
        )

    try:
        result = apply(state, RunCommand(command))
    except (InvalidTransition, ValueError):
        raise

    # Elapsed only ever moves forward. A client reporting a smaller value after a
    # reconnect is reporting a stale reading, not time travelling backwards.
    next_elapsed = max(current_elapsed_ms, elapsed_ms)
    return CommandOutcome(
        state=result.current,
        applied=True,
        elapsed_ms=next_elapsed,
        last_segment_id=segment_id or current_segment_id,
        sequence=sequence,
    )


def recovery_point(plan: SessionPlanV2, last_segment_id: str | None) -> tuple[str | None, int]:
    """Where to resume after process death — SDD section 5.3.

    Resume never lands mid-utterance. If the last thing confirmed was a speech
    segment, that segment restarts from its beginning: repeating up to one
    sentence is better than joining one halfway through.
    """
    if last_segment_id is None:
        return None, 0

    offsets = plan.timeline.offsets_ms()
    for segment, offset in zip(plan.timeline.segments, offsets, strict=True):
        if segment.id == last_segment_id:
            return segment.id, offset
    # The plan no longer contains that segment: start over rather than guess.
    return None, 0


def new_command_id() -> str:
    return uuid.uuid4().hex
