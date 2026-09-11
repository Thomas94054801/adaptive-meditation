"""Public-language guard for practice knowledge.

Two product invariants are machine-checked here rather than trusted to review:

1. wellness positioning, not medical diagnosis or treatment;
2. source-grounded internally, non-sectarian in user-facing wording.

The guard runs over every field that can reach a user (public titles, public
names and prompt templates). Internal provenance fields such as ``source_basis``
are deliberately exempt - that is the whole point of keeping them internal.
"""

from __future__ import annotations

import re

# Word-boundary matched so that "health" does not trip "heal" and "therapist"
# does trip "therap".
MEDICAL_TERMS: frozenset[str] = frozenset(
    {
        "diagnose",
        "diagnosis",
        "treat",
        "treatment",
        "cure",
        "heal",
        "healing",
        "therapy",
        "therapist",
        "therapeutic",
        "clinical",
        "clinically",
        "patient",
        "disorder",
        "depression",
        "ptsd",
        "medication",
        "prescribe",
        "prescription",
        "symptom",
        "symptoms",
        "remedy",
    }
)

SECTARIAN_TERMS: frozenset[str] = frozenset(
    {
        "buddha",
        "buddhist",
        "buddhism",
        "dharma",
        "dhamma",
        "sutta",
        "sutra",
        "nirvana",
        "nibbana",
        "karma",
        "samsara",
        "sangha",
        "zen",
        "vipassana",
        "anapanasati",
        "satipatthana",
        "metta",
        "vedananupassana",
        "cittanupassana",
        "kayanupassana",
        "mantra",
        "chakra",
        "prayer",
        "pray",
        "sacred",
        "divine",
        "god",
        "soul",
        "spirit",
        "spiritual",
        "enlightenment",
        "guru",
        "monk",
        "temple",
        "ritual",
    }
)

_TOKEN_RE = re.compile(r"[a-z]+")


class PublicLanguageError(ValueError):
    """Raised when user-facing knowledge text violates a product invariant."""


def find_violations(text: str) -> list[str]:
    """Return the denied terms present in ``text``, sorted for determinism."""
    tokens = set(_TOKEN_RE.findall(text.lower()))
    return sorted(tokens & (MEDICAL_TERMS | SECTARIAN_TERMS))


def assert_public_language(text: str, *, where: str) -> None:
    violations = find_violations(text)
    if violations:
        raise PublicLanguageError(
            f"{where}: user-facing text contains denied terminology {violations}. "
            "V1 wording is non-clinical and non-sectarian; source provenance stays "
            "in internal metadata."
        )
