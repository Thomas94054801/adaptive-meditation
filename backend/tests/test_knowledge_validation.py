"""Knowledge cross-validation tests - SDD section 15.5.

Each test mutates a copy of the real knowledge files on disk and asserts the
loader refuses it. The failure modes the SDD names are checked directly rather
than inferred from a happy-path load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.domain.practice.catalog import (
    PRACTICES_FILE,
    PROTOCOLS_FILE,
    KnowledgeCatalog,
    KnowledgeValidationError,
    load_catalog,
)
from app.domain.practice.language import PublicLanguageError, find_violations
from app.domain.recommendation.rules import PracticeId

from .conftest import KNOWLEDGE_DIR


def write_variant(
    tmp_path: Path,
    *,
    practices: dict[str, Any] | None = None,
    protocols: dict[str, Any] | None = None,
) -> Path:
    """Copy the real knowledge files into tmp_path, optionally replacing one."""
    source_practices = yaml.safe_load((KNOWLEDGE_DIR / PRACTICES_FILE).read_text())
    source_protocols = yaml.safe_load((KNOWLEDGE_DIR / PROTOCOLS_FILE).read_text())
    (tmp_path / PRACTICES_FILE).write_text(yaml.safe_dump(practices or source_practices))
    (tmp_path / PROTOCOLS_FILE).write_text(yaml.safe_dump(protocols or source_protocols))
    return tmp_path


def load_protocols() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((KNOWLEDGE_DIR / PROTOCOLS_FILE).read_text())
    return data


def test_real_knowledge_files_load(catalog: KnowledgeCatalog) -> None:
    assert catalog.practices_schema_version == 1
    assert catalog.protocols_schema_version == 1
    assert len(catalog.practices) == len(catalog.protocols_by_practice) == 6


def test_every_rule_selectable_practice_has_a_protocol(catalog: KnowledgeCatalog) -> None:
    for practice_id in PracticeId:
        assert catalog.has_executable_protocol(practice_id.value), practice_id


def test_protocol_referencing_an_unknown_practice_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["practice_id"] = "not_a_practice"
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(KnowledgeValidationError, match="unknown practice_id"):
        load_catalog(directory)


def test_practice_without_a_protocol_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"] = protocols["protocols"][:-1]
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(KnowledgeValidationError, match="without an executable protocol"):
        load_catalog(directory)


def test_protocol_supporting_no_duration_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["duration_supported"] = []
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(Exception, match="duration_supported|at least 1"):
        load_catalog(directory)


def test_duration_below_the_stage_minimums_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["duration_supported"] = [1, 3, 5, 10, 15, 20]
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(KnowledgeValidationError, match="stage minimums"):
        load_catalog(directory)


def test_duration_above_the_stage_maximums_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["duration_supported"] = [3, 5, 10, 15, 20, 45]
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(KnowledgeValidationError, match="stage maximums"):
        load_catalog(directory)


def test_inverted_density_range_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["guidance_density_range"] = [0.75, 0.30]
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(Exception, match="inverted"):
        load_catalog(directory)


def test_duplicate_protocol_for_one_practice_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    duplicate = dict(protocols["protocols"][0])
    duplicate["id"] = duplicate["id"] + "_copy"
    protocols["protocols"].append(duplicate)
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(KnowledgeValidationError, match="more than one protocol"):
        load_catalog(directory)


def test_missing_knowledge_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeValidationError, match="not found"):
        load_catalog(tmp_path)


# --- public language invariants ----------------------------------------------


def test_clinical_wording_in_a_prompt_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["stages"][0]["prompt_template"] = (
        "This practice will treat your anxiety disorder and cure insomnia."
    )
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(PublicLanguageError, match="denied terminology"):
        load_catalog(directory)


def test_sectarian_wording_in_a_public_title_is_rejected(tmp_path: Path) -> None:
    protocols = load_protocols()
    protocols["protocols"][0]["public_title"] = "Anapanasati (Buddhist breath practice)"
    directory = write_variant(tmp_path, protocols=protocols)
    with pytest.raises(PublicLanguageError, match="denied terminology"):
        load_catalog(directory)


def test_internal_source_basis_is_exempt(catalog: KnowledgeCatalog) -> None:
    """Source provenance is retained internally and is not a language violation."""
    bases = {practice.source_basis for practice in catalog.practices.values()}
    assert "anapanasati" in bases
    assert find_violations("anapanasati") == ["anapanasati"]
    for practice in catalog.practices.values():
        assert practice.user_facing_source_label is None
        assert find_violations(practice.public_name) == []


def test_public_names_match_the_product_vocabulary(catalog: KnowledgeCatalog) -> None:
    expected = {
        "breath_awareness": "Breath Awareness",
        "body_awareness": "Body Awareness",
        "feeling_tone": "Feeling Tone",
        "thought_observation": "Thought Observation",
        "kindness": "Kindness Practice",
        "open_awareness": "Open Awareness",
    }
    assert {pid: p.public_name for pid, p in catalog.practices.items()} == expected


def test_language_guard_uses_word_boundaries() -> None:
    """ "health" must not trip "heal"; "therapist" must trip "therap"."""
    assert find_violations("healthy and present") == []
    assert find_violations("your therapist said") == ["therapist"]
