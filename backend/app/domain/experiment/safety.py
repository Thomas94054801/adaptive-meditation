"""What an experiment is allowed to vary.

An experiment that could reach a safety decision would make every safety test
conditional on a variant. The boundary is enforced here rather than trusted to
review: a variant may only carry presentation fields, and the recommendation an
experiment sees has already been decided.
"""

from __future__ import annotations

from typing import Final

# Fields an experiment may influence. Presentation only.
ALLOWED_EXPERIMENT_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "explanation_copy",
        "presentation_ordering",
        "cta_copy",
        "onboarding_copy",
    }
)

# Fields no experiment may ever influence. Listed explicitly so the test that
# guards them reads as a statement of intent rather than a list of strings.
PROTECTED_FROM_EXPERIMENTS: Final[frozenset[str]] = frozenset(
    {
        "practice_id",
        "practice_eligibility",
        "duration_minutes",
        "guidance_density",
        "safety_routing",
        "contraindications",
        "minimum_experience",
        "data_deletion",
        "privacy_choices",
        "subscription_state",
        "crisis_handling",
    }
)


class ExperimentBoundaryError(RuntimeError):
    """Raised when an experiment would touch a protected field."""


def assert_presentation_only(surface: str) -> None:
    if surface in PROTECTED_FROM_EXPERIMENTS:
        raise ExperimentBoundaryError(
            f"{surface!r} is protected from experimentation. An experiment may "
            "vary presentation, never a practice or safety decision."
        )
    if surface not in ALLOWED_EXPERIMENT_SURFACES:
        raise ExperimentBoundaryError(
            f"{surface!r} is not a declared experiment surface. Add it to "
            "ALLOWED_EXPERIMENT_SURFACES with a reason, or do not vary it."
        )
