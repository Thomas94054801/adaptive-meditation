"""Version identifiers carried on every recommendation.

Program001 had a single ``recommendation_version``. That conflated three things
that change independently, so a stored record could not tell you whether a
different answer came from new machinery, new rules or new knowledge.
"""

from __future__ import annotations

from enum import StrEnum

# The scoring/selection machinery itself.
ENGINE_VERSION = "2"


class RuleSetVersion(StrEnum):
    """Which rule tables produced a recommendation."""

    V1 = "1"
    V2 = "2"


DEFAULT_RULE_SET_VERSION = RuleSetVersion.V2

# Knowledge protocol revision. Mirrors the knowledge file schema_version.
DEFAULT_PROTOCOL_VERSION = "2"

# The single field Program001 wrote. A stored record carrying only this is
# interpreted as engine 1 / rules 1 / protocols 1.
LEGACY_VERSION_FIELD = "recommendation_version"
LEGACY_ENGINE_VERSION = "1"
