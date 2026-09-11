"""Rule-set selection.

Both rule sets are first-class and both stay runnable forever: v1 because
stored v1 recommendations must remain replayable, v2 because it is production.
The offline comparator runs the two against the *same* catalog so a diff
isolates the rule change rather than mixing in a knowledge change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.practice.catalog import KnowledgeCatalog, KnowledgeValidationError
from app.domain.recommendation import rules_v2
from app.domain.recommendation.rules import PracticeId, ReasonCode, select_practice
from app.domain.recommendation.scoring import SCORE_MAX, Candidate, Exclusion, RuleOutcome
from app.domain.recommendation.versions import RuleSetVersion
from app.domain.state.models import StateVector


@runtime_checkable
class RuleSet(Protocol):
    version: str

    def evaluate(self, state: StateVector, catalog: KnowledgeCatalog) -> RuleOutcome: ...


class V1RuleSet:
    """Program001's priority-ordered cascade, preserved exactly.

    A cascade has no ranking, so the single match is reported at SCORE_MAX and
    every other practice is excluded as ``not_selected_by_cascade``. The score
    is structurally meaningless here; it exists so v1 and v2 share one result
    type rather than forcing every consumer to branch on the version.
    """

    version = RuleSetVersion.V1.value

    def evaluate(self, state: StateVector, catalog: KnowledgeCatalog) -> RuleOutcome:
        selection = select_practice(state)
        codes: tuple[ReasonCode, ...] = selection.reason_codes
        chosen: PracticeId

        if catalog.has_executable_protocol(selection.primary.value):
            chosen = selection.primary
        elif selection.fallback is not None and catalog.has_executable_protocol(
            selection.fallback.value
        ):
            chosen = selection.fallback
            codes = (*codes, ReasonCode.FALLBACK_PRACTICE_USED)
        else:
            raise KnowledgeValidationError(
                f"selected practice {selection.primary.value!r} has no executable "
                "protocol and no usable fallback"
            )

        exclusions = tuple(
            Exclusion(practice_id, "not_selected_by_cascade")
            for practice_id in rules_v2.PRACTICE_ORDER
            if practice_id is not chosen
        )
        return RuleOutcome(
            candidates=(Candidate(chosen, SCORE_MAX, codes),),
            exclusions=exclusions,
            rule_set_version=self.version,
        )


class V2RuleSet:
    """Scored ranking over eligible practices."""

    version = RuleSetVersion.V2.value

    def evaluate(self, state: StateVector, catalog: KnowledgeCatalog) -> RuleOutcome:
        return rules_v2.evaluate(state, catalog)


RULE_SETS: dict[str, type[V1RuleSet] | type[V2RuleSet]] = {
    RuleSetVersion.V1.value: V1RuleSet,
    RuleSetVersion.V2.value: V2RuleSet,
}


def build_rule_set(version: str) -> RuleSet:
    try:
        return RULE_SETS[version]()
    except KeyError:
        raise ValueError(f"unknown rule set version {version!r}") from None
