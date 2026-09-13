"""Program004R Slice B — resolutions, validated rather than trusted.

The interesting tests here are the rejections. A resolution is computed by the
device and posted afterwards, so the only thing standing between a tampered or
buggy client and a corrupt session record is what this module refuses.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.state.models import CheckIn, StateVector
from app.domain.timeline.resolution import (
    CANONICALIZATION_VERSION,
    TIMING_POLICY_VERSION,
    MeasurementSource,
    ResolutionInvalid,
    ResolvedSegment,
    ResolvedTimeline,
    recompute_hash,
    resolve_for,
    validate_against_plan,
)
from app.domain.timeline.segments import BellSegment, SilenceSegment, SpeechSegment
from app.domain.timeline.service import plan_session
from tests.test_playback_api import CHECK_IN, start_session

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "timing_fixtures.v1.json"


@pytest.fixture
def plan(catalog: KnowledgeCatalog, engine: RecommendationEngine):
    state = StateVector.from_check_in(CheckIn.model_validate(CHECK_IN))
    return plan_session(catalog, engine.recommend(state), state).plan


def audio_hashes(plan) -> dict[str, str]:
    """A plausible hash per speech and bell segment."""
    hashes: dict[str, str] = {}
    for index, segment in enumerate(plan.timeline.segments):
        if isinstance(segment, SpeechSegment | BellSegment):
            hashes[segment.id] = f"{index:02d}" + "a" * 62
    return hashes


# --------------------------------------------------------------------------- #
# The cross-language contract, from the Python side
# --------------------------------------------------------------------------- #


def test_the_fixture_file_exists_and_declares_our_versions() -> None:
    document = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert document["canonicalization_version"] == CANONICALIZATION_VERSION
    assert document["timing_policy_version"] == TIMING_POLICY_VERSION
    assert document["cases"]


def test_every_fixture_reproduces_its_recorded_hash() -> None:
    """The same assertion the Dart suite makes, from this side."""
    document = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for case in document["cases"]:
        resolution = ResolvedTimeline.from_dict(case["input"])
        assert resolution.canonical() == case["expected_canonical"], case["name"]
        assert resolution.resolution_hash == case["expected_canonical_sha256"], case["name"]


def test_nfc_normalisation_is_applied_to_the_canonical_form() -> None:
    """Decomposed and composed spellings of the same text must agree."""
    composed = ResolvedTimeline(
        plan_hash="a" * 64,
        locale="fr-FR",
        revision=1,
        timing_policy_version=TIMING_POLICY_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=MeasurementSource.DEVICE_REPORTED,
        audio_mode="audible",
        segments=(ResolvedSegment("speech_relâche", "speech", 7000, "f" * 64),),
        extended_by_ms=0,
        absorbed_ms=0,
        outcome="on_target",
    )
    decomposed = ResolvedTimeline(
        plan_hash="a" * 64,
        locale="fr-FR",
        revision=1,
        timing_policy_version=TIMING_POLICY_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=MeasurementSource.DEVICE_REPORTED,
        audio_mode="audible",
        segments=(ResolvedSegment("speech_relâche", "speech", 7000, "f" * 64),),
        extended_by_ms=0,
        absorbed_ms=0,
        outcome="on_target",
    )
    assert composed.resolution_hash == decomposed.resolution_hash


def test_no_floats_reach_the_canonical_form() -> None:
    """Float formatting is exactly where two runtimes diverge, so there are none.

    Checked on the canonical string itself, not just the input types: an int
    that got stringified through a float would show up here as "8000.0".
    """
    document = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for case in document["cases"]:
        canonical = case["expected_canonical"]
        assert ".0" not in canonical, case["name"]
        assert "e+" not in canonical.lower(), case["name"]
        for segment in case["input"]["segments"]:
            assert isinstance(segment["effective_ms"], int), case["name"]
            assert not isinstance(segment["effective_ms"], bool), case["name"]


# --------------------------------------------------------------------------- #
# resolve_timing finally has a caller
# --------------------------------------------------------------------------- #


def test_resolution_is_built_from_the_timing_policy(plan) -> None:
    """G4 closes here: the silence allocation comes from resolve_timing."""
    speech = plan.timeline.speech()
    measured = {s.id: s.estimated_ms + 1500 for s in speech}
    resolution = resolve_for(plan, measured, audio_hashes=audio_hashes(plan))

    assert resolution.absorbed_ms > 0
    assert resolution.outcome in {"absorbed", "absorbed_at_floor", "duration_extended"}
    assert len(resolution.segments) == len(plan.timeline.segments)
    for resolved, planned in zip(resolution.segments, plan.timeline.segments, strict=True):
        assert resolved.segment_id == planned.id


def test_a_measured_overrun_never_breaches_a_floor(plan) -> None:
    measured = {s.id: s.estimated_ms * 40 for s in plan.timeline.speech()}
    resolution = resolve_for(plan, measured, audio_hashes=audio_hashes(plan))
    floors = {s.id: s.min_ms for s in plan.timeline.segments if isinstance(s, SilenceSegment)}
    for segment in resolution.segments:
        floor = floors.get(segment.segment_id)
        if floor is not None:
            assert segment.effective_ms >= floor
    assert resolution.extended_by_ms > 0


def test_an_implausible_duration_is_refused() -> None:
    with pytest.raises(ResolutionInvalid, match="plausible"):
        ResolvedSegment("speech_0", "speech", 40 * 60 * 1000)


def test_a_negative_duration_is_refused() -> None:
    with pytest.raises(ResolutionInvalid, match="negative"):
        ResolvedSegment("speech_0", "speech", -1)


# --------------------------------------------------------------------------- #
# Content validation, not a sign check
# --------------------------------------------------------------------------- #


def test_a_valid_resolution_passes(plan) -> None:
    resolution = resolve_for(plan, {}, audio_hashes=audio_hashes(plan))
    validate_against_plan(resolution, plan)


def test_a_resolution_for_another_plan_is_refused(plan) -> None:
    resolution = resolve_for(plan, {}, audio_hashes=audio_hashes(plan))
    forged = ResolvedTimeline(
        plan_hash="b" * 64,
        locale=resolution.locale,
        revision=1,
        timing_policy_version=TIMING_POLICY_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=resolution.measurement_source,
        audio_mode=resolution.audio_mode,
        segments=resolution.segments,
        extended_by_ms=0,
        absorbed_ms=0,
        outcome="on_target",
    )
    with pytest.raises(ResolutionInvalid, match="different plan"):
        validate_against_plan(forged, plan)


def test_a_reordered_timeline_is_refused(plan) -> None:
    """Set comparison would accept this. Order is part of the session."""
    resolution = resolve_for(plan, {}, audio_hashes=audio_hashes(plan))
    swapped = list(resolution.segments)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    reordered = ResolvedTimeline(
        plan_hash=resolution.plan_hash,
        locale=resolution.locale,
        revision=1,
        timing_policy_version=TIMING_POLICY_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=resolution.measurement_source,
        audio_mode=resolution.audio_mode,
        segments=tuple(swapped),
        extended_by_ms=0,
        absorbed_ms=0,
        outcome="on_target",
    )
    with pytest.raises(ResolutionInvalid, match="plan says"):
        validate_against_plan(reordered, plan)


def test_a_silence_below_its_floor_is_refused(plan) -> None:
    resolution = resolve_for(plan, {}, audio_hashes=audio_hashes(plan))
    tampered = tuple(
        ResolvedSegment(
            s.segment_id, s.kind, 1 if s.kind == "silence" else s.effective_ms, s.audio_sha256
        )
        for s in resolution.segments
    )
    below = ResolvedTimeline(
        plan_hash=resolution.plan_hash,
        locale=resolution.locale,
        revision=1,
        timing_policy_version=TIMING_POLICY_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=resolution.measurement_source,
        audio_mode=resolution.audio_mode,
        segments=tampered,
        extended_by_ms=0,
        absorbed_ms=0,
        outcome="on_target",
    )
    with pytest.raises(ResolutionInvalid, match="floor"):
        validate_against_plan(below, plan)


def test_an_audible_resolution_without_audio_hashes_is_refused(plan) -> None:
    """Claiming audible delivery with no audio is the core dishonesty to block."""
    resolution = resolve_for(plan, {}, audio_mode="audible")
    with pytest.raises(ResolutionInvalid, match="audio hash"):
        validate_against_plan(resolution, plan)


def test_silent_mode_needs_no_audio_hashes(plan) -> None:
    resolution = resolve_for(
        plan,
        {},
        audio_mode="silent_by_choice",
        measurement_source=MeasurementSource.PLAN_ESTIMATE,
    )
    validate_against_plan(resolution, plan)


def test_an_unknown_version_is_refused(plan) -> None:
    resolution = resolve_for(plan, {}, audio_hashes=audio_hashes(plan))
    future = ResolvedTimeline(
        plan_hash=resolution.plan_hash,
        locale=resolution.locale,
        revision=1,
        timing_policy_version="99",
        canonicalization_version=CANONICALIZATION_VERSION,
        measurement_source=resolution.measurement_source,
        audio_mode=resolution.audio_mode,
        segments=resolution.segments,
        extended_by_ms=0,
        absorbed_ms=0,
        outcome="on_target",
    )
    with pytest.raises(ResolutionInvalid, match="timing_policy_version"):
        validate_against_plan(future, plan)


def test_the_hash_is_recomputed_from_content(plan) -> None:
    resolution = resolve_for(plan, {}, audio_hashes=audio_hashes(plan))
    assert recompute_hash(resolution) == resolution.resolution_hash


# --------------------------------------------------------------------------- #
# Over HTTP
# --------------------------------------------------------------------------- #


def post_resolution(
    client: TestClient, headers: dict[str, str], session_id: str, payload: dict[str, object]
):
    return client.post(f"/v1/sessions/{session_id}/resolution", json=payload, headers=headers)


def resolution_payload(session: dict[str, object], **overrides: object) -> dict[str, object]:
    """Build a resolution the way a device would, from the plan it received."""
    plan_v2 = session["plan_v2"]
    segments: list[dict[str, object]] = []
    for index, segment in enumerate(plan_v2["segments"]):  # type: ignore[index]
        kind = segment["kind"]
        if kind == "speech":
            effective = segment["estimated_ms"]
        elif kind == "silence":
            effective = segment["target_ms"]
        elif kind == "bell":
            effective = segment["duration_ms"]
        else:
            effective = 0
        entry: dict[str, object] = {
            "segment_id": segment["id"],
            "kind": kind,
            "effective_ms": effective,
        }
        if kind in {"speech", "bell"}:
            entry["audio_sha256"] = f"{index:02d}" + "a" * 62
        segments.append(entry)

    body: dict[str, object] = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "plan_hash": plan_v2["plan_hash"],  # type: ignore[index]
        "locale": plan_v2["locale"],  # type: ignore[index]
        "revision": 1,
        "timing_policy_version": TIMING_POLICY_VERSION,
        "measurement_source": "device_reported",
        "audio_mode": "audible",
        "segments": segments,
        "extended_by_ms": 0,
        "absorbed_ms": 0,
        "outcome": "on_target",
    }
    body.update(overrides)
    body["total_ms"] = sum(int(s["effective_ms"]) for s in segments)  # type: ignore[arg-type]
    rebuilt = ResolvedTimeline.from_dict({**body, "resolution_hash": "0" * 64})
    body["resolution_hash"] = rebuilt.resolution_hash
    return body


def test_a_device_resolution_is_accepted_and_validated(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = start_session(client, guest_headers)
    response = post_resolution(
        client, guest_headers, str(session["id"]), resolution_payload(session)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["server_validated"] is True
    assert body["created"] is True
    assert body["revision"] == 1


def test_reposting_the_same_resolution_is_idempotent(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = start_session(client, guest_headers)
    payload = resolution_payload(session)
    first = post_resolution(client, guest_headers, str(session["id"]), payload)
    second = post_resolution(client, guest_headers, str(session["id"]), payload)
    assert first.json()["created"] is True
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["resolution_hash"] == first.json()["resolution_hash"]


def test_the_same_revision_with_different_content_is_a_conflict(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """A2: a resolution is never edited in place."""
    session = start_session(client, guest_headers)
    post_resolution(client, guest_headers, str(session["id"]), resolution_payload(session))

    altered = resolution_payload(session)
    altered["segments"][0]["effective_ms"] = 2500  # type: ignore[index]
    rebuilt = ResolvedTimeline.from_dict({**altered, "resolution_hash": "0" * 64})
    altered["total_ms"] = rebuilt.total_ms
    altered["resolution_hash"] = ResolvedTimeline.from_dict(
        {**altered, "resolution_hash": "0" * 64}
    ).resolution_hash

    response = post_resolution(client, guest_headers, str(session["id"]), altered)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resolution_revision_conflict"


def test_a_forged_hash_is_rejected(client: TestClient, guest_headers: dict[str, str]) -> None:
    session = start_session(client, guest_headers)
    payload = resolution_payload(session)
    payload["resolution_hash"] = "f" * 64
    response = post_resolution(client, guest_headers, str(session["id"]), payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resolution_hash_mismatch"


def test_a_tampered_duration_is_rejected(client: TestClient, guest_headers: dict[str, str]) -> None:
    """Recomputed content validation catches what a sign check would not."""
    session = start_session(client, guest_headers)
    payload = resolution_payload(session)
    for segment in payload["segments"]:  # type: ignore[attr-defined]
        if segment["kind"] == "silence":
            segment["effective_ms"] = 5
    payload["total_ms"] = sum(int(s["effective_ms"]) for s in payload["segments"])  # type: ignore[attr-defined,arg-type]
    payload["resolution_hash"] = ResolvedTimeline.from_dict(
        {**payload, "resolution_hash": "0" * 64}
    ).resolution_hash

    response = post_resolution(client, guest_headers, str(session["id"]), payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resolution_rejected"
    assert "floor" in response.json()["error"]["message"]


def test_a_resolution_claiming_audible_with_no_audio_is_rejected(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = start_session(client, guest_headers)
    payload = resolution_payload(session)
    for segment in payload["segments"]:  # type: ignore[attr-defined]
        segment.pop("audio_sha256", None)
    payload["resolution_hash"] = ResolvedTimeline.from_dict(
        {**payload, "resolution_hash": "0" * 64}
    ).resolution_hash
    response = post_resolution(client, guest_headers, str(session["id"]), payload)
    assert response.status_code == 422
    assert "audio hash" in response.json()["error"]["message"]


def test_a_second_revision_is_stored_alongside_the_first(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    """A repair keeps the old revision, so the played prefix stays explainable."""
    session = start_session(client, guest_headers)
    post_resolution(client, guest_headers, str(session["id"]), resolution_payload(session))
    second = resolution_payload(session, revision=2)
    response = post_resolution(client, guest_headers, str(session["id"]), second)
    assert response.status_code == 201
    assert response.json()["revision"] == 2
    assert response.json()["created"] is True


def test_a_resolution_is_isolated_between_guests(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = start_session(client, guest_headers)
    other = {"X-Guest-Id": str(uuid.uuid4())}
    response = post_resolution(client, other, str(session["id"]), resolution_payload(session))
    assert response.status_code == 404
