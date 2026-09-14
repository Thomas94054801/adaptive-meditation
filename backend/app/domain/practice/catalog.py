"""Knowledge catalog: load and cross-validate practices and protocols.

Memory: the catalog holds one ``Practice`` per practice family and one
``Protocol`` per family - six of each in V1, loaded once at import of the
application and shared read-only. It does not grow with request volume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.domain.practice.language import assert_public_language
from app.domain.practice.models import Practice, Protocol

# Knowledge is versioned on disk. v1 is frozen: it is the comparator baseline
# and the V1 replay fixture, and must never be edited.
KNOWLEDGE_VERSIONS: tuple[int, ...] = (1, 2)
DEFAULT_KNOWLEDGE_VERSION = 2

PRACTICES_FILE = "practices.v1.yaml"
PROTOCOLS_FILE = "protocols.v1.yaml"


def practices_file(version: int) -> str:
    return f"practices.v{version}.yaml"


def protocols_file(version: int) -> str:
    return f"protocols.v{version}.yaml"


class KnowledgeValidationError(ValueError):
    """Raised when the knowledge files are internally inconsistent."""


@dataclass(frozen=True, slots=True)
class KnowledgeCatalog:
    """Immutable practice/protocol knowledge, validated at load time."""

    practices: dict[str, Practice]
    protocols_by_practice: dict[str, Protocol]
    practices_schema_version: int
    protocols_schema_version: int
    knowledge_version: int = DEFAULT_KNOWLEDGE_VERSION

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


def load_catalog(knowledge_dir: Path, version: int = DEFAULT_KNOWLEDGE_VERSION) -> KnowledgeCatalog:
    """Load and cross-validate the knowledge files.

    Raises :class:`KnowledgeValidationError` if a protocol points at an unknown
    practice, a practice has no executable protocol, a declared duration cannot
    be rendered by the protocol's own stage bounds, or user-facing text breaks
    the public-language invariants.
    """
    if version not in KNOWLEDGE_VERSIONS:
        raise KnowledgeValidationError(f"unknown knowledge version {version!r}")
    practices_raw = _load_yaml(knowledge_dir / practices_file(version))
    protocols_raw = _load_yaml(knowledge_dir / protocols_file(version))

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
        _validate_returning_templates(protocol)
        protocols[protocol.practice_id] = protocol

    missing = sorted(set(practices) - set(protocols))
    if missing:
        raise KnowledgeValidationError(f"practices without an executable protocol: {missing}")

    for practice in practices.values():
        protocol = protocols[practice.id]
        low, high = practice.duration_range
        if low > high:
            raise KnowledgeValidationError(
                f"practice {practice.id!r} declares an inverted duration_range"
            )
        outside = [d for d in protocol.duration_supported if not low <= d <= high]
        if outside:
            raise KnowledgeValidationError(
                f"protocol {protocol.id!r} supports durations {outside} outside the "
                f"practice's declared duration_range {list(practice.duration_range)}"
            )
        if practice.guidance_density_range != (0.0, 1.0):
            p_low, p_high = practice.guidance_density_range
            r_low, r_high = protocol.guidance_density_range
            if r_low < p_low or r_high > p_high:
                raise KnowledgeValidationError(
                    f"protocol {protocol.id!r} density range "
                    f"{list(protocol.guidance_density_range)} escapes the practice's "
                    f"{list(practice.guidance_density_range)}"
                )

    return KnowledgeCatalog(
        practices=practices,
        protocols_by_practice=protocols,
        practices_schema_version=int(practices_raw.get("schema_version", 0)),
        protocols_schema_version=int(protocols_raw.get("schema_version", 0)),
        knowledge_version=version,
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


_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def placeholders(text: str) -> frozenset[str]:
    """The ``${name}`` substitutions a template asks for."""
    return frozenset(_PLACEHOLDER.findall(text))


def validate_returning_template(canonical: str, returning: str, *, where: str) -> None:
    """Program005 policy 1 - what a returning-guest opening may be.

    Same public-language rules as every prompt, the same placeholder set (so
    the planner substitutes the same values), and no more words than the
    canonical text: the returning variant drops orientation a person has
    already heard; it never adds instruction. None of this is a claim of
    semantic equivalence - that is a content review, done by reading.
    """
    assert_public_language(returning, where=where)
    if placeholders(returning) != placeholders(canonical):
        raise KnowledgeValidationError(
            f"{where}: placeholders {sorted(placeholders(returning))} differ from the "
            f"canonical template's {sorted(placeholders(canonical))}"
        )
    if len(returning.split()) > len(canonical.split()):
        raise KnowledgeValidationError(
            f"{where}: {len(returning.split())} words exceeds the canonical "
            f"{len(canonical.split())}"
        )


def _validate_returning_templates(protocol: Protocol) -> None:
    for index, stage in enumerate(protocol.stages):
        if stage.returning_prompt_template is None:
            continue
        where = f"protocol {protocol.id}.{stage.id}.returning_prompt_template"
        if index != 0:
            # Policy 1 varies the orientation only. A later stage is the
            # practice itself, and the practice does not change with familiarity.
            raise KnowledgeValidationError(f"{where}: only the first stage may vary")
        validate_returning_template(
            stage.prompt_template, stage.returning_prompt_template, where=where
        )


@lru_cache(maxsize=8)
def get_catalog(knowledge_dir: Path, version: int = DEFAULT_KNOWLEDGE_VERSION) -> KnowledgeCatalog:
    """Process-wide cached catalog. Bounded at eight (directory, version) pairs."""
    return load_catalog(knowledge_dir, version)
