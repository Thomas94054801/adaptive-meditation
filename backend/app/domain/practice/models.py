"""Practice and protocol knowledge models.

These mirror ``knowledge/practices.v1.yaml`` and ``knowledge/protocols.v1.yaml``.
The knowledge files are the source of truth; the engine never invents a practice
or a protocol stage.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.state.models import Goal

Density = Annotated[float, Field(ge=0.0, le=1.0)]


class Practice(BaseModel):
    """A practice family.

    ``source_basis`` is internal provenance. It is never required in a public
    API response and is stripped by :meth:`public_view`; ``user_facing_source_label``
    is the only field allowed to carry source wording into the UI, and it is
    null for every V1 practice.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    public_name: str
    intent: str
    suitable_for: tuple[Goal, ...]
    source_basis: str
    user_facing_source_label: str | None = None
    default_guidance_density: Density

    def public_view(self) -> dict[str, object]:
        return {
            "id": self.id,
            "public_name": self.public_name,
            "intent": self.intent,
            "suitable_for": [goal.value for goal in self.suitable_for],
        }


class ProtocolStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    intent: str
    min_seconds: int = Field(ge=1)
    max_seconds: int = Field(ge=1)
    prompt_template: str = Field(min_length=1, max_length=600)
    silence_after_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_bounds(self) -> ProtocolStage:
        if self.max_seconds < self.min_seconds:
            raise ValueError(f"stage {self.id}: max_seconds < min_seconds")
        if self.silence_after_seconds > self.min_seconds:
            raise ValueError(
                f"stage {self.id}: silence_after_seconds exceeds min_seconds, "
                "the stage could not hold its own silence at the shortest duration"
            )
        return self


class Protocol(BaseModel):
    """An executable protocol for one practice family."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: int = Field(ge=1)
    practice_id: str
    public_title: str
    duration_supported: tuple[int, ...] = Field(min_length=1)
    guidance_density_range: tuple[Density, Density]
    stages: tuple[ProtocolStage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_envelope(self) -> Protocol:
        low, high = self.guidance_density_range
        if high < low:
            raise ValueError(f"protocol {self.id}: guidance_density_range is inverted")
        if len(set(self.duration_supported)) != len(self.duration_supported):
            raise ValueError(f"protocol {self.id}: duplicate duration in duration_supported")
        stage_ids = [stage.id for stage in self.stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError(f"protocol {self.id}: duplicate stage id")
        return self

    @property
    def min_total_seconds(self) -> int:
        return sum(stage.min_seconds for stage in self.stages)

    @property
    def max_total_seconds(self) -> int:
        return sum(stage.max_seconds for stage in self.stages)

    def supports_duration(self, minutes: int) -> bool:
        if minutes not in self.duration_supported:
            return False
        total = minutes * 60
        return self.min_total_seconds <= total <= self.max_total_seconds

    def accepts_density(self, density: float) -> bool:
        low, high = self.guidance_density_range
        return low <= density <= high
