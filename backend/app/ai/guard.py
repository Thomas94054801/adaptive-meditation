"""Envelope guard for AI personalization.

The product invariant is that a generative provider may not silently change the
practice family, the duration or the guidance density that the deterministic
engine selected. "Silently" is the operative word: this guard makes the attempt
visible and discards the personalization rather than trusting it.

Program005 adds wording admissibility. A result that survives the envelope can
still be unusable: a stage other than the first was rewritten (policy 1 varies
the orientation only), a placeholder the planner substitutes went missing, a
prompt came back empty or over the knowledge file's length bound, or the
public-language guard rejects it. Any of those keeps the deterministic wording
for every stage - a half-accepted result would freeze a definition nobody
reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.providers.base import PersonalizationRequest, PersonalizationResult
from app.domain.practice.catalog import placeholders
from app.domain.practice.language import PublicLanguageError, assert_public_language

# Mirrors ProtocolStage.prompt_template's bound; generated wording may not
# exceed what an authored prompt may.
MAX_PROMPT_LENGTH = 600


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


def check_wording(
    request: PersonalizationRequest, result: PersonalizationResult
) -> tuple[str, ...]:
    """Return the wording rules the result broke, in a fixed order.

    Assumes the stage count already matched (``check_envelope`` runs first);
    the pairwise walk below would otherwise mask a count mismatch.
    """
    violations: list[str] = []
    for index, (original, candidate) in enumerate(
        zip(request.stage_prompts, result.stage_prompts, strict=False)
    ):
        if not isinstance(candidate, str):
            violations.append(f"not_string[{index}]")
            continue
        if candidate == original:
            continue
        if index != 0:
            # Only the orientation stage may vary under policy 1. A later
            # stage is the practice, and the practice is not the provider's.
            violations.append(f"protected_stage[{index}]")
            continue
        if not candidate.strip():
            violations.append(f"empty[{index}]")
            continue
        if len(candidate) > MAX_PROMPT_LENGTH:
            violations.append(f"length[{index}]")
            continue
        if placeholders(candidate) != placeholders(original):
            violations.append(f"placeholders[{index}]")
            continue
        try:
            assert_public_language(candidate, where=f"stage {index}")
        except PublicLanguageError:
            violations.append(f"public_language[{index}]")
    return tuple(violations)


def apply_personalization(
    request: PersonalizationRequest,
    result: PersonalizationResult,
    *,
    strict: bool = False,
) -> GuardOutcome:
    """Accept personalized wording only if the envelope and the wording survived.

    On violation the deterministic wording is kept for every stage.
    ``strict=True`` raises instead, which is what the provider test suite
    asserts against.
    """
    violations = check_envelope(request, result)
    if not violations:
        violations = check_wording(request, result)
    if violations:
        if strict:
            raise EnvelopeViolation(
                f"provider {result.provider_id!r} changed protected fields: {list(violations)}"
            )
        return GuardOutcome(request.stage_prompts, personalized=False, violations=violations)
    return GuardOutcome(result.stage_prompts, personalized=True, violations=())
