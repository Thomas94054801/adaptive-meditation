"""Input validation tests - SDD section 15.3."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.state.models import CheckIn

BASE: dict[str, object] = {
    "goal": "stress",
    "stress": 5,
    "energy": 5,
    "mental_activity": 5,
    "sleepiness": 5,
    "available_minutes": 10,
    "experience_level": "beginner",
}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"stress": -1}, id="stress_below_zero"),
        pytest.param({"stress": 11}, id="stress_above_ten"),
        pytest.param({"energy": -1}, id="energy_below_zero"),
        pytest.param({"mental_activity": 11}, id="mental_activity_above_ten"),
        pytest.param({"sleepiness": -3}, id="sleepiness_below_zero"),
        pytest.param({"goal": "anxiety"}, id="unsupported_goal"),
        pytest.param({"goal": ""}, id="empty_goal"),
        pytest.param({"available_minutes": 7}, id="unsupported_duration"),
        pytest.param({"available_minutes": 0}, id="zero_duration"),
        pytest.param({"available_minutes": 60}, id="duration_above_maximum"),
        pytest.param({"experience_level": "expert"}, id="unsupported_experience"),
        pytest.param({"stress": "high"}, id="non_numeric_scale"),
        pytest.param({"extra_field": 1}, id="unknown_field"),
    ],
)
def test_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CheckIn.model_validate(BASE | overrides)


@pytest.mark.parametrize("field", sorted(BASE))
def test_every_field_is_required(field: str) -> None:
    payload = {key: value for key, value in BASE.items() if key != field}
    with pytest.raises(ValidationError):
        CheckIn.model_validate(payload)


def test_boundary_values_are_accepted() -> None:
    for value in (0, 10):
        CheckIn.model_validate(
            BASE | {"stress": value, "energy": value, "mental_activity": value, "sleepiness": value}
        )


def test_check_in_is_immutable() -> None:
    check_in = CheckIn.model_validate(BASE)
    with pytest.raises(ValidationError):
        check_in.stress = 9  # type: ignore[misc]
