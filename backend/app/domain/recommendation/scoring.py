"""Candidate scoring types.

The score is an ordinal ranking aid on a 0..100 integer scale. It is **not** a
probability: it has no calibration and no frequency interpretation, and must
never be normalised to 1.0, rendered as a percentage, or described as a
confidence. Naming it ``score`` and bounding it as an integer is deliberate -
a float in 0..1 invites exactly the misreading this comment forbids.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.recommendation.rules import PracticeId, ReasonCode

SCORE_MIN = 0
SCORE_MAX = 100


def clamp_score(value: int) -> int:
    return max(SCORE_MIN, min(SCORE_MAX, value))


@dataclass(frozen=True, slots=True)
class Candidate:
    """One scored, eligible practice."""

    practice_id: PracticeId
    score: int
    reason_codes: tuple[ReasonCode, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "practice_id": self.practice_id.value,
            "score": self.score,
            "reason_codes": [code.value for code in self.reason_codes],
        }


@dataclass(frozen=True, slots=True)
class Exclusion:
    """A practice removed before scoring, and why.

    Recorded rather than discarded so the offline evaluator can distinguish
    "ranked last" from "never eligible" - they have different fixes.
    """

    practice_id: PracticeId
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"practice_id": self.practice_id.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """The full result of evaluating a rule set against one state."""

    candidates: tuple[Candidate, ...]
    exclusions: tuple[Exclusion, ...]
    rule_set_version: str

    @property
    def winner(self) -> Candidate:
        if not self.candidates:
            raise ValueError("rule set produced no eligible candidate")
        return self.candidates[0]

    def as_dict(self) -> dict[str, object]:
        return {
            "rule_set_version": self.rule_set_version,
            "candidates": [c.as_dict() for c in self.candidates],
            "exclusions": [e.as_dict() for e in self.exclusions],
        }
