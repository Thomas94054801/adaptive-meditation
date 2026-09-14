"""Program005 personalization — familiarity, presentation variant, provenance.

Presentation only. Everything here runs after the deterministic engine has
chosen the practice, the duration and the guidance density, and nothing here
can reach back into that decision: the inputs are a count of completed
sessions, a preference flag and an optional provider, and the only output is
which words the first stage speaks plus a record of why.

One module rather than a service/manager/registry stack, because the whole
policy is two tiers, one variant and one guarded call.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.ai.guard import apply_personalization
from app.ai.providers.base import AIProvider, PersonalizationRequest, PersonalizationResult
from app.ai.providers.null import NullAIProvider
from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.timeline.definition import (
    ContentSource,
    SessionDefinition,
    StageContent,
    definition_for,
)

# Bumped whenever the tier rule, the cap, the variant mapping or the guard
# rules change, so a stored provenance can be read with the policy that wrote
# it. Adding an input to familiarity requires a bump.
POLICY_VERSION = "1"

# The count saturates here. 100 means "at least 100", never a known total.
EVIDENCE_CAP = 100


class FamiliarityTier(StrEnum):
    NEW = "new"
    RETURNING = "returning"


class PresentationVariant(StrEnum):
    CANONICAL = "canonical"
    RETURNING = "returning"


class FallbackReason(StrEnum):
    """Why the provider's wording was not used. Exactly one applies."""

    PROVIDER_ABSENT = "provider_absent"
    ADAPTIVE_WORDING_DISABLED = "adaptive_wording_disabled"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_TIMEOUT = "provider_timeout"
    MALFORMED_OUTPUT = "malformed_output"
    ENVELOPE_VIOLATION = "envelope_violation"
    WORDING_REJECTED = "wording_rejected"


class Reason(StrEnum):
    """The one factual reason shown to the person. The client owns the strings."""

    RETURNING_TO_THIS_PRACTICE = "returning_to_this_practice"
    FIRST_TIME_WITH_THIS_PRACTICE = "first_time_with_this_practice"
    ADAPTIVE_WORDING_OFF = "adaptive_wording_off"
    NO_HISTORY_AVAILABLE = "no_history_available"


ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {"practice_id", "duration_minutes", "guidance_density", "stage_count"}
)


class PersonalizationInvariantError(RuntimeError):
    """The personalized definition differs from the canonical one outside wording."""


@dataclass(frozen=True, slots=True)
class Familiarity:
    """What the history says, and nothing about what it means."""

    tier: FamiliarityTier
    evidence_count: int
    evidence_capped: bool
    # False when there was no guest identity to look up. The tier is NEW
    # either way; this only chooses the reason shown.
    history_available: bool

    @classmethod
    def from_count(cls, count: int, *, history_available: bool = True) -> Familiarity:
        if count < 0:
            raise ValueError("evidence_count cannot be negative")
        bounded = min(count, EVIDENCE_CAP)
        return cls(
            tier=FamiliarityTier.RETURNING if bounded >= 1 else FamiliarityTier.NEW,
            evidence_count=bounded,
            evidence_capped=bounded >= EVIDENCE_CAP,
            history_available=history_available,
        )

    @classmethod
    def unknown(cls) -> Familiarity:
        return cls.from_count(0, history_available=False)


def variant_definition(
    catalog: KnowledgeCatalog,
    practice_id: str,
    variant: PresentationVariant,
    locale: str = "en-US",
) -> SessionDefinition:
    """The frozen definition for one variant.

    A new immutable object every time: the catalog's protocol is read, never
    written, and the canonical definition's bytes and id are exactly what
    Program004 produced. The returning variant differs from it in the first
    stage's template only, so its content hash differs by construction.
    """
    canonical = definition_for(catalog, practice_id, locale=locale)
    if variant is PresentationVariant.CANONICAL:
        return canonical
    returning = catalog.protocol_for(practice_id).stages[0].returning_prompt_template
    if returning is None:
        return canonical
    first = dataclasses.replace(canonical.stages[0], prompt_template=returning)
    return dataclasses.replace(canonical, stages=(first, *canonical.stages[1:]))


def assert_envelope_preserved(
    canonical: SessionDefinition, personalized: SessionDefinition
) -> None:
    """The check behind PERS-03/04/05: only the first stage's words may differ."""
    problems: list[str] = []
    for field in ("practice_id", "protocol_id", "public_title", "locale", "version"):
        if getattr(canonical, field) != getattr(personalized, field):
            problems.append(field)
    if len(canonical.stages) != len(personalized.stages):
        problems.append("stage_count")
    else:
        for index, (a, b) in enumerate(zip(canonical.stages, personalized.stages, strict=True)):
            for field in ("stage_id", "intent", "silence_after_seconds", "min_silence_seconds"):
                if getattr(a, field) != getattr(b, field):
                    problems.append(f"{field}[{index}]")
            if index != 0 and a.prompt_template != b.prompt_template:
                problems.append(f"prompt_template[{index}]")
    if problems:
        raise PersonalizationInvariantError(f"personalization changed protected fields: {problems}")


@dataclass(frozen=True, slots=True)
class Provenance:
    """Frozen with the session. Answers what, why, which policy, whether AI."""

    familiarity: Familiarity
    presentation_variant: PresentationVariant
    adaptive_wording_enabled: bool
    provider_id: str
    ai_attempted: bool
    ai_accepted: bool
    fallback_reason: FallbackReason | None
    schema_version: int = 1
    policy_version: str = POLICY_VERSION

    @property
    def personalized(self) -> bool:
        return self.presentation_variant is not PresentationVariant.CANONICAL or self.ai_accepted

    @property
    def reason(self) -> Reason:
        if not self.adaptive_wording_enabled:
            return Reason.ADAPTIVE_WORDING_OFF
        if not self.familiarity.history_available:
            return Reason.NO_HISTORY_AVAILABLE
        if self.familiarity.tier is FamiliarityTier.RETURNING:
            return Reason.RETURNING_TO_THIS_PRACTICE
        return Reason.FIRST_TIME_WITH_THIS_PRACTICE

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "personalization_policy_version": self.policy_version,
            "familiarity_tier": self.familiarity.tier.value,
            "evidence_count": self.familiarity.evidence_count,
            "evidence_capped": self.familiarity.evidence_capped,
            "presentation_variant": self.presentation_variant.value,
            "adaptive_wording_enabled": self.adaptive_wording_enabled,
            "personalized": self.personalized,
            "provider_id": self.provider_id,
            "ai_attempted": self.ai_attempted,
            "ai_accepted": self.ai_accepted,
            "fallback_reason": self.fallback_reason.value if self.fallback_reason else None,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class Personalized:
    definition: SessionDefinition
    provenance: Provenance


def _well_formed(result: object, expected_stages: int) -> bool:
    """A provider result the guard can even look at."""
    if not isinstance(result, PersonalizationResult):
        return False
    prompts = result.stage_prompts
    if not isinstance(prompts, tuple | list):
        return False
    if len(prompts) != expected_stages:
        # A count mismatch is an envelope violation, which the guard reports
        # by name; it is well-formed enough to reach it.
        return isinstance(result.practice_id, str)
    return isinstance(result.practice_id, str) and isinstance(result.duration_minutes, int)


def personalize(
    *,
    catalog: KnowledgeCatalog,
    practice_id: str,
    duration_minutes: int,
    guidance_density: float,
    familiarity: Familiarity,
    adaptive_wording: bool,
    provider: AIProvider | None,
    locale: str = "en-US",
) -> Personalized:
    """Choose the variant, offer it to the provider once, keep what survives.

    Never raises for anything the provider does. One attempt, no retry: a
    session is never late because wording was.
    """
    canonical = definition_for(catalog, practice_id, locale=locale)

    if not adaptive_wording:
        return Personalized(
            canonical,
            Provenance(
                familiarity=familiarity,
                presentation_variant=PresentationVariant.CANONICAL,
                adaptive_wording_enabled=False,
                provider_id=NullAIProvider.provider_id
                if provider is None
                else provider.provider_id,
                ai_attempted=False,
                ai_accepted=False,
                fallback_reason=FallbackReason.ADAPTIVE_WORDING_DISABLED,
            ),
        )

    wanted = (
        PresentationVariant.RETURNING
        if familiarity.tier is FamiliarityTier.RETURNING
        else PresentationVariant.CANONICAL
    )
    definition = variant_definition(catalog, practice_id, wanted, locale=locale)
    # A practice without a returning template stays canonical, and says so.
    variant = (
        PresentationVariant.RETURNING
        if definition.definition_id != canonical.definition_id
        else PresentationVariant.CANONICAL
    )

    if provider is None:
        provider = NullAIProvider()
    ai_attempted = provider.provider_id != NullAIProvider.provider_id
    ai_accepted = False
    fallback: FallbackReason | None = None if ai_attempted else FallbackReason.PROVIDER_ABSENT

    request = PersonalizationRequest(
        practice_id=practice_id,
        duration_minutes=duration_minutes,
        guidance_density=guidance_density,
        stage_prompts=tuple(stage.prompt_template for stage in definition.stages),
        presentation_variant=variant.value,
    )
    try:
        result = provider.personalize(request)
    except TimeoutError:
        # Recorded because the provider raised it; nothing here can abort a
        # call that does not return.
        fallback = FallbackReason.PROVIDER_TIMEOUT
    except Exception:
        fallback = FallbackReason.PROVIDER_ERROR
    else:
        if not _well_formed(result, len(request.stage_prompts)):
            fallback = FallbackReason.MALFORMED_OUTPUT
        elif ai_attempted:
            outcome = apply_personalization(request, result)
            if outcome.personalized:
                ai_accepted = True
                stages = tuple(
                    StageContent(
                        stage_id=stage.stage_id,
                        intent=stage.intent,
                        prompt_template=prompt,
                        silence_after_seconds=stage.silence_after_seconds,
                        min_silence_seconds=stage.min_silence_seconds,
                    )
                    for stage, prompt in zip(definition.stages, outcome.stage_prompts, strict=True)
                )
                definition = dataclasses.replace(
                    definition, stages=stages, source=ContentSource.GENERATED
                )
            elif any(v.split("[")[0] in ENVELOPE_FIELDS for v in outcome.violations):
                fallback = FallbackReason.ENVELOPE_VIOLATION
            else:
                fallback = FallbackReason.WORDING_REJECTED

    assert_envelope_preserved(canonical, definition)
    return Personalized(
        definition,
        Provenance(
            familiarity=familiarity,
            presentation_variant=variant,
            adaptive_wording_enabled=True,
            provider_id=provider.provider_id,
            ai_attempted=ai_attempted,
            ai_accepted=ai_accepted,
            fallback_reason=fallback,
        ),
    )
