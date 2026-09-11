"""Pre-generation safety routing boundary.

Program001 has no free-text prompt path to a model. This interface exists so
that when one is added it cannot be wired directly: the router sits in front of
generation by construction.

This is not a crisis classifier and makes no clinical detection claim. The only
implementation shipped in Program001 is :class:`NoopSafetyRouter`, which allows
everything and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class SafetyAction(StrEnum):
    ALLOW = "allow"
    BLOCK_GENERATION = "block_generation"
    SHOW_SUPPORT_RESOURCES = "show_support_resources"


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    action: SafetyAction
    router_id: str
    detail: str = ""

    @property
    def allows_generation(self) -> bool:
        return self.action is SafetyAction.ALLOW


@runtime_checkable
class SafetyRouter(Protocol):
    def classify(self, text: str) -> SafetyDecision: ...


class NoopSafetyRouter:
    """Allows all text. Claims no detection capability of any kind."""

    router_id = "noop"

    def classify(self, text: str) -> SafetyDecision:
        return SafetyDecision(
            action=SafetyAction.ALLOW,
            router_id=self.router_id,
            detail="no classification performed",
        )
