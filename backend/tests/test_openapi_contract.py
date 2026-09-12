"""OpenAPI consistency tests.

api/openapi.v1.yaml is generated from the implementation. These tests assert the
committed file is current, that it is a valid OpenAPI 3.1 document, and that the
contract elements the SDD names survive regeneration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from openapi_spec_validator import validate

from app.settings import Settings

from .conftest import BACKEND_ROOT, KNOWLEDGE_DIR

SPEC_PATH = BACKEND_ROOT.parent / "api" / "openapi.v1.yaml"


@pytest.fixture(scope="module")
def committed_spec() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return document


def test_committed_spec_matches_the_implementation() -> None:
    """Regenerating must be a no-op; otherwise the contract has drifted."""
    import sys

    sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
    from export_openapi import build_document  # type: ignore[import-not-found]

    assert (
        SPEC_PATH.read_text(encoding="utf-8") == build_document()
    ), "api/openapi.v1.yaml is stale; run python backend/scripts/export_openapi.py"


def test_spec_is_a_valid_openapi_document(committed_spec: dict[str, Any]) -> None:
    validate(committed_spec)
    assert committed_spec["openapi"].startswith("3.1")


def test_required_paths_and_operations(committed_spec: dict[str, Any]) -> None:
    expected = {
        ("/v1/check-ins", "post"): "createCheckIn",
        ("/v1/recommendations", "post"): "createRecommendation",
        ("/v1/sessions", "post"): "createSession",
        ("/v1/sessions/{session_id}/start", "post"): "startSession",
        ("/v1/sessions/{session_id}/feedback", "post"): "submitSessionFeedback",
        ("/v1/sessions/{session_id}", "get"): "getSession",
        ("/v1/sessions/{session_id}/playback", "post"): "applyPlaybackCommand",
        ("/v1/sessions/{session_id}/playback", "get"): "getPlaybackState",
        ("/v1/sessions/{session_id}/events", "post"): "appendSessionEvents",
        ("/v1/sessions/{session_id}/prepare", "post"): "prepareSession",
        ("/v1/recommendations/candidates", "post"): "createRecommendationCandidates",
        ("/v1/sessions/history", "get"): "listSessionHistory",
        ("/v1/me/export", "get"): "exportGuestData",
        ("/v1/me/data", "delete"): "deleteGuestData",
        ("/healthz", "get"): "healthz",
        ("/privacy", "get"): "privacyPolicy",
        ("/terms", "get"): "termsOfUse",
        ("/support", "get"): "support",
        ("/delete-account", "get"): "deleteAccountInfo",
    }
    for (path, method), operation_id in expected.items():
        assert path in committed_spec["paths"], path
        assert committed_spec["paths"][path][method]["operationId"] == operation_id


def test_response_codes_match_the_contract(committed_spec: dict[str, Any]) -> None:
    paths = committed_spec["paths"]
    assert "201" in paths["/v1/check-ins"]["post"]["responses"]
    assert "200" in paths["/v1/recommendations"]["post"]["responses"]
    assert "201" in paths["/v1/sessions"]["post"]["responses"]
    assert "204" in paths["/v1/sessions/{session_id}/feedback"]["post"]["responses"]
    assert "404" in paths["/v1/sessions/{session_id}/feedback"]["post"]["responses"]
    assert "409" in paths["/v1/sessions"]["post"]["responses"]


def test_playback_contract_declares_its_idempotency_fields(
    committed_spec: dict[str, Any],
) -> None:
    """A client cannot retry safely if the contract does not promise it can."""
    schema = committed_spec["components"]["schemas"]["PlaybackCommandRequest"]
    assert set(schema["required"]) >= {"command", "command_id", "sequence"}
    assert schema["additionalProperties"] is False
    commands = set(_enum_values(committed_spec, schema["properties"]["command"]))
    assert commands == {
        "prepare",
        "resolved",
        "unresolvable",
        "start",
        "pause",
        "resume",
        "interrupt",
        "interruption_ended",
        "complete",
        "abandon",
        "fail",
        "recover",
    }
    state = committed_spec["components"]["schemas"]["PlaybackStateResponse"]
    for field in ("run_state", "applied", "resume_segment_id", "resume_offset_ms"):
        assert field in state["properties"], field

    paths = committed_spec["paths"]
    playback = paths["/v1/sessions/{session_id}/playback"]["post"]["responses"]
    # A conflict is a real outcome of an illegal transition; the contract says so.
    assert "409" in playback
    assert "404" in playback


def test_the_event_journal_contract_is_a_closed_set(committed_spec: dict[str, Any]) -> None:
    schema = committed_spec["components"]["schemas"]["SessionEventRequest"]
    types = set(_enum_values(committed_spec, schema["properties"]["event_type"]))
    assert "segment_started" in types
    assert "vibes" not in types
    batch = committed_spec["components"]["schemas"]["SessionEventBatchRequest"]
    # Bounded: an unbounded batch is an unbounded write amplification.
    assert batch["properties"]["events"]["maxItems"] == 200


def test_the_export_contract_includes_the_playback_journal(
    committed_spec: dict[str, Any],
) -> None:
    """A table the export omits is a privacy defect, so the contract pins it."""
    schema = committed_spec["components"]["schemas"]["GuestExportResponse"]
    assert "playback_events" in schema["properties"]


def test_check_in_schema_keeps_its_declared_bounds(committed_spec: dict[str, Any]) -> None:
    schema = committed_spec["components"]["schemas"]["CheckIn"]
    assert set(schema["required"]) == {
        "goal",
        "stress",
        "energy",
        "mental_activity",
        "sleepiness",
        "available_minutes",
        "experience_level",
    }
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert properties["available_minutes"]["enum"] == [3, 5, 10, 15, 20]
    for field in ("stress", "energy", "mental_activity", "sleepiness"):
        assert properties[field]["minimum"] == 0
        assert properties[field]["maximum"] == 10

    goals = set(_enum_values(committed_spec, properties["goal"]))
    assert goals == {"stress", "overthinking", "focus", "sleep", "emotional_reset", "general"}
    levels = set(_enum_values(committed_spec, properties["experience_level"]))
    assert levels == {"beginner", "intermediate", "experienced"}


def test_v2_version_fields_are_in_the_contract(committed_spec: dict[str, Any]) -> None:
    schema = committed_spec["components"]["schemas"]["RecommendationResponse"]
    for field in ("engine_version", "rule_set_version", "protocol_version", "state_fingerprint"):
        assert field in schema["properties"], field
    assert "recommendation_version" not in schema["properties"]


def test_guest_routes_declare_their_identity_header(committed_spec: dict[str, Any]) -> None:
    for path in ("/v1/sessions/history", "/v1/me/export"):
        operation = committed_spec["paths"][path]["get"]
        names = {p.get("name") for p in operation.get("parameters", [])}
        assert "X-Guest-Id" in names, path


def test_candidate_score_is_declared_as_a_bounded_integer(
    committed_spec: dict[str, Any],
) -> None:
    """The contract must not let a score be read as a probability."""
    schema = committed_spec["components"]["schemas"]["CandidateResponse"]
    score = schema["properties"]["score"]
    assert score["type"] == "integer"
    assert score["minimum"] == 0
    assert score["maximum"] == 100


def test_recommendation_schema_requires_the_contract_fields(
    committed_spec: dict[str, Any],
) -> None:
    schema = committed_spec["components"]["schemas"]["RecommendationResponse"]
    assert {
        "practice_id",
        "duration_minutes",
        "guidance_density",
        "reason_codes",
    } <= set(schema["required"])
    assert schema["properties"]["guidance_density"]["minimum"] == 0.0
    assert schema["properties"]["guidance_density"]["maximum"] == 1.0


def test_spec_exposes_no_internal_source_mapping(committed_spec: dict[str, Any]) -> None:
    """Internal provenance must not become part of the public contract."""
    serialized = yaml.safe_dump(committed_spec)
    for internal in ("source_basis", "anapanasati", "satipatthana", "metta"):
        assert internal not in serialized


def test_export_script_check_mode_agrees(tmp_path: Path) -> None:
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "export_openapi.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _enum_values(spec: dict[str, Any], node: dict[str, Any]) -> list[str]:
    """Resolve an inline enum or a local $ref to one."""
    if "enum" in node:
        values: list[str] = node["enum"]
        return values
    if "allOf" in node:
        node = node["allOf"][0]
    ref = node.get("$ref", "")
    name = ref.rsplit("/", 1)[-1]
    return list(spec["components"]["schemas"][name]["enum"])


def test_settings_default_knowledge_dir_resolves() -> None:
    assert Settings().knowledge_dir == KNOWLEDGE_DIR
