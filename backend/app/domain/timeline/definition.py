"""Immutable, versioned session definitions — SDD section 4C.

Program001 to 003 read guidance straight out of the knowledge YAML at plan time.
That is fine for choosing a practice and useless as an audit trail: edit a prompt
and every past session silently starts describing words nobody heard.

A definition freezes the content a session used. Editing content produces a new
version; it never mutates one that a session already references.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.practice.models import Protocol
from app.domain.timeline.segments import canonical_json, content_hash

DEFINITION_SCHEMA_VERSION = 1


class ContentSource(StrEnum):
    """Where the words came from. Generated content is never planned unvalidated."""

    AUTHORED = "authored"
    GENERATED = "generated"
    LOCALIZED = "localized"


@dataclass(frozen=True, slots=True)
class StageContent:
    """One stage's frozen wording."""

    stage_id: str
    intent: str
    prompt_template: str
    silence_after_seconds: int
    min_silence_seconds: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "intent": self.intent,
            "prompt_template": self.prompt_template,
            "silence_after_seconds": self.silence_after_seconds,
            "min_silence_seconds": self.min_silence_seconds,
        }


@dataclass(frozen=True, slots=True)
class SessionDefinition:
    """A frozen, addressable version of one practice's guidance.

    ``definition_id`` is the content hash, so identity and content cannot drift
    apart: two definitions with the same id necessarily say the same thing.
    """

    practice_id: str
    protocol_id: str
    public_title: str
    locale: str
    source: ContentSource
    version: int
    schema_version: int
    stages: tuple[StageContent, ...]

    @property
    def definition_id(self) -> str:
        return content_hash(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "practice_id": self.practice_id,
            "protocol_id": self.protocol_id,
            "public_title": self.public_title,
            "locale": self.locale,
            "source": self.source.value,
            "version": self.version,
            "stages": [stage.as_dict() for stage in self.stages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionDefinition:
        """Rebuild a stored definition. This is what makes old sessions readable."""
        return cls(
            practice_id=data["practice_id"],
            protocol_id=data["protocol_id"],
            public_title=data["public_title"],
            locale=data["locale"],
            source=ContentSource(data["source"]),
            version=int(data["version"]),
            schema_version=int(data["schema_version"]),
            stages=tuple(
                StageContent(
                    stage_id=s["stage_id"],
                    intent=s["intent"],
                    prompt_template=s["prompt_template"],
                    silence_after_seconds=int(s["silence_after_seconds"]),
                    min_silence_seconds=int(s["min_silence_seconds"]),
                )
                for s in data["stages"]
            ),
        )

    def canonical(self) -> str:
        return canonical_json(self.as_dict())


# A silence may shrink to this fraction of its target before it stops reading as
# intentional silence and starts reading as the app having stopped working.
MIN_SILENCE_FRACTION = 0.4
ABSOLUTE_MIN_SILENCE_SECONDS = 5


def definition_from_protocol(
    protocol: Protocol, public_title: str, locale: str = "en-US", version: int = 1
) -> SessionDefinition:
    """Freeze a knowledge-file protocol into a definition.

    The knowledge files remain the authoring surface; this is the point at which
    their current contents stop being able to change under a session's feet.
    """
    stages = tuple(
        StageContent(
            stage_id=stage.id,
            intent=stage.intent,
            prompt_template=stage.prompt_template,
            silence_after_seconds=stage.silence_after_seconds,
            min_silence_seconds=max(
                ABSOLUTE_MIN_SILENCE_SECONDS
                if stage.silence_after_seconds >= ABSOLUTE_MIN_SILENCE_SECONDS
                else stage.silence_after_seconds,
                int(stage.silence_after_seconds * MIN_SILENCE_FRACTION),
            ),
        )
        for stage in protocol.stages
    )
    return SessionDefinition(
        practice_id=protocol.practice_id,
        protocol_id=protocol.id,
        public_title=public_title,
        locale=locale,
        source=ContentSource.AUTHORED,
        version=version,
        schema_version=DEFINITION_SCHEMA_VERSION,
        stages=stages,
    )


def definition_for(
    catalog: KnowledgeCatalog, practice_id: str, locale: str = "en-US"
) -> SessionDefinition:
    protocol = catalog.protocol_for(practice_id)
    practice = catalog.practice(practice_id)
    return definition_from_protocol(
        protocol,
        public_title=practice.public_name,
        locale=locale,
        version=protocol.version,
    )
