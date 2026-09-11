"""Envelope guard for AI personalization.

The product invariant is that a generative provider may not silently change the
practice family, the duration or the guidance density that the deterministic
engine selected. "Silently" is the operative word: this guard makes the attempt
visible and discards the personalization rather than trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.providers.base import PersonalizationRequest, PersonalizationResult


class EnvelopeViolation(ValueError):
    """Raised when a provider returns a result outside the deterministic envelope."""


@dataclass(frozen=True, slots=True)
class GuardOutcome:
    stage_prompts: tuple[str, ...]
    personalized: bool
    violations: tuple[str, ...]


def check_envelope(
    request: PersonalizationRequest, result: PersonalizationResult
) -> tuple[str, ...]:
    """Return the envelope fields the provider changed, in a fixed order."""
    violations: list[str] = []
    if result.practice_id != request.practice_id:
        violations.append("practice_id")
    if result.duration_minutes != request.duration_minutes:
        violations.append("duration_minutes")
    if result.guidance_density != request.guidance_density:
        violations.append("guidance_density")
    if len(result.stage_prompts) != len(request.stage_prompts):
        violations.append("stage_count")
    return tuple(violations)


def apply_personalization(
    request: PersonalizationRequest,
    result: PersonalizationResult,
    *,
    strict: bool = False,
) -> GuardOutcome:
    """Accept personalized wording only if the envelope survived it.

    On violation the deterministic wording is kept. ``strict=True`` raises
    instead, which is what the provider test suite asserts against.
    """
    violations = check_envelope(request, result)
    if violations:
        if strict:
            raise EnvelopeViolation(
                f"provider {result.provider_id!r} changed protected fields: {list(violations)}"
            )
        return GuardOutcome(request.stage_prompts, personalized=False, violations=violations)
    return GuardOutcome(result.stage_prompts, personalized=True, violations=())
