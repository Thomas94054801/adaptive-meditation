"""Knowledge catalog: load and cross-validate practices and protocols.

Memory: the catalog holds one ``Practice`` per practice family and one
``Protocol`` per family - six of each in V1, loaded once at import of the
application and shared read-only. It does not grow with request volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.domain.practice.language import assert_public_language
from app.domain.practice.models import Practice, Protocol

PRACTICES_FILE = "practices.v1.yaml"
PROTOCOLS_FILE = "protocols.v1.yaml"


class KnowledgeValidationError(ValueError):
    """Raised when the knowledge files are internally inconsistent."""


@dataclass(frozen=True, slots=True)
class KnowledgeCatalog:
    """Immutable practice/protocol knowledge, validated at load time."""

    practices: dict[str, Practice]
    protocols_by_practice: dict[str, Protocol]
    practices_schema_version: int
    protocols_schema_version: int

    def practice(self, practice_id: str) -> Practice:
        try:
            return self.practices[practice_id]
        except KeyError:
            raise KnowledgeValidationError(f"unknown practice_id {practice_id!r}") from None

    def protocol_for(self, practice_id: str) -> Protocol:
        try:
            return self.protocols_by_practice[practice_id]
        except KeyError:
            raise KnowledgeValidationError(
                f"no executable protocol for practice_id {practice_id!r}"
            ) from None

    def has_executable_protocol(self, practice_id: str) -> bool:
        return practice_id in self.practices and practice_id in self.protocols_by_practice

    def practice_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.practices))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise KnowledgeValidationError(f"knowledge file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise KnowledgeValidationError(f"knowledge file {path} must contain a mapping")
    return data


def load_catalog(knowledge_dir: Path) -> KnowledgeCatalog:
    """Load and cross-validate the knowledge files.

    Raises :class:`KnowledgeValidationError` if a protocol points at an unknown
    practice, a practice has no executable protocol, a declared duration cannot
    be rendered by the protocol's own stage bounds, or user-facing text breaks
    the public-language invariants.
    """
    practices_raw = _load_yaml(knowledge_dir / PRACTICES_FILE)
    protocols_raw = _load_yaml(knowledge_dir / PROTOCOLS_FILE)

    practices: dict[str, Practice] = {}
    for entry in practices_raw.get("practices", []):
        practice = Practice.model_validate(entry)
        if practice.id in practices:
            raise KnowledgeValidationError(f"duplicate practice id {practice.id!r}")
        assert_public_language(practice.public_name, where=f"practice {practice.id}.public_name")
        if practice.user_facing_source_label is not None:
            assert_public_language(
                practice.user_facing_source_label,
                where=f"practice {practice.id}.user_facing_source_label",
            )
        practices[practice.id] = practice

    if not practices:
        raise KnowledgeValidationError("practices file declares no practices")

    protocols: dict[str, Protocol] = {}
    for entry in protocols_raw.get("protocols", []):
        protocol = Protocol.model_validate(entry)
        if protocol.practice_id not in practices:
            raise KnowledgeValidationError(
                f"protocol {protocol.id!r} references unknown practice_id "
                f"{protocol.practice_id!r}"
            )
        if protocol.practice_id in protocols:
            raise KnowledgeValidationError(
                f"more than one protocol declared for practice {protocol.practice_id!r}"
            )
        _validate_protocol_renderability(protocol)
        assert_public_language(protocol.public_title, where=f"protocol {protocol.id}.public_title")
        for stage in protocol.stages:
            assert_public_language(
                stage.prompt_template, where=f"protocol {protocol.id}.{stage.id}.prompt_template"
            )
        protocols[protocol.practice_id] = protocol

    missing = sorted(set(practices) - set(protocols))
    if missing:
        raise KnowledgeValidationError(f"practices without an executable protocol: {missing}")

    return KnowledgeCatalog(
        practices=practices,
        protocols_by_practice=protocols,
        practices_schema_version=int(practices_raw.get("schema_version", 0)),
        protocols_schema_version=int(protocols_raw.get("schema_version", 0)),
    )


def _validate_protocol_renderability(protocol: Protocol) -> None:
    if not protocol.duration_supported:
        raise KnowledgeValidationError(f"protocol {protocol.id!r} supports no duration")
    for minutes in protocol.duration_supported:
        total = minutes * 60
        if total < protocol.min_total_seconds:
            raise KnowledgeValidationError(
                f"protocol {protocol.id!r} declares {minutes} min but its stage minimums "
                f"need {protocol.min_total_seconds}s"
            )
        if total > protocol.max_total_seconds:
            raise KnowledgeValidationError(
                f"protocol {protocol.id!r} declares {minutes} min but its stage maximums "
                f"only reach {protocol.max_total_seconds}s"
            )


@lru_cache(maxsize=4)
def get_catalog(knowledge_dir: Path) -> KnowledgeCatalog:
    """Process-wide cached catalog. Bounded at four directories (app + tests)."""
    return load_catalog(knowledge_dir)
