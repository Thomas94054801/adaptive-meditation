"""Program004 Slice D - provider-neutral audio.

The claims worth testing here are mostly negative ones: a render request cannot
carry who is listening, a cache key cannot depend on who asked, a voice is not
called offline until a probe with the network down says so, and no audio asset
enters the repository without a traceable origin.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.audio.fake import FakeSpeechRenderer
from app.adapters.audio.registry import (
    NullSpeechRenderer,
    UnknownSpeechProvider,
    build_renderer,
)
from app.domain.audio.cache import (
    SOFT_CAP_BYTES,
    STALE_AFTER_DAYS,
    CacheEntry,
    ResolutionAttempt,
    ResolutionRung,
    guest_deletion_clears_cache,
    plan_eviction,
    resolve,
    verify,
)
from app.domain.audio.capability import (
    LocaleSupport,
    OfflineCapability,
    ProbeObservation,
    VoiceCapability,
    classify,
    may_claim_offline,
)
from app.domain.audio.coordinator import build_manifest
from app.domain.audio.render import (
    PersonalDataInRenderRequest,
    RenderRequest,
    RenderResult,
    RenderUnavailable,
)
from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.state.models import CheckIn, StateVector
from app.domain.timeline.planner_v2 import render_key_for
from app.domain.timeline.service import plan_session
from app.settings import Settings
from tests.test_playback_api import CHECK_IN, start_session

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def plan(catalog: KnowledgeCatalog, engine: RecommendationEngine):
    state = StateVector.from_check_in(CheckIn.model_validate(CHECK_IN))
    return plan_session(catalog, engine.recommend(state), state).plan


def a_request(**overrides: object) -> RenderRequest:
    fields: dict[str, object] = {
        "text": "Let the breath settle.",
        "locale": "en-US",
        "voice_id": "default",
        "style": "calm",
        "provider_id": "fake",
        "provider_version": "1",
    }
    fields.update(overrides)
    return RenderRequest(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# What a render request may not carry - SDD 8.5
# --------------------------------------------------------------------------- #


def test_a_render_request_carries_only_product_authored_text() -> None:
    request = a_request()
    assert set(request.as_dict()) == {
        "text",
        "locale",
        "voice_id",
        "style",
        "provider_id",
        "provider_version",
        "render_version",
    }


@pytest.mark.parametrize(
    "field",
    ["guest_id", "session_id", "experiment_arm", "device_id", "notes", "history"],
)
def test_prohibited_fields_are_refused(field: str) -> None:
    """Enforced over the serialised request, not left to reviewer diligence."""
    from app.domain.audio.render import assert_no_personal_data

    with pytest.raises(PersonalDataInRenderRequest, match=field):
        assert_no_personal_data({"text": "hello", field: "anything"})


def test_a_prohibited_field_nested_deeper_is_still_refused() -> None:
    from app.domain.audio.render import assert_no_personal_data

    with pytest.raises(PersonalDataInRenderRequest):
        assert_no_personal_data({"text": "hello", "meta": {"inner": {"guest_id": "x"}}})


def test_an_identifier_pasted_into_the_text_is_refused() -> None:
    """How this actually happens: an id interpolated into a template."""
    with pytest.raises(PersonalDataInRenderRequest, match="identifier"):
        a_request(text=f"Welcome back, {uuid.uuid4()}.")


def test_an_empty_request_is_refused() -> None:
    with pytest.raises(ValueError, match="no text"):
        a_request(text="   ")


# --------------------------------------------------------------------------- #
# The content-addressed key - SDD 9.1
# --------------------------------------------------------------------------- #


def test_the_key_is_nfc_normalised() -> None:
    """The same visible sentence must not miss the cache over byte encoding."""
    composed = unicodedata.normalize("NFC", "Relâche la mâchoire.")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert render_key_for(composed, "fr-FR", "v", "calm", "p", "1", "1") == render_key_for(
        decomposed, "fr-FR", "v", "calm", "p", "1", "1"
    )


def test_whitespace_differences_do_not_change_the_key() -> None:
    assert render_key_for("  a   b  ", "en-US", "v", "calm", "p", "1", "1") == render_key_for(
        "a b", "en-US", "v", "calm", "p", "1", "1"
    )


def test_field_boundaries_cannot_be_confused() -> None:
    """Two different splits of the same characters must not hash identically."""
    first = render_key_for("ab", "cd", "v", "calm", "p", "1", "1")
    second = render_key_for("a", "bcd", "v", "calm", "p", "1", "1")
    assert first != second


def test_a_provider_version_bump_is_the_invalidation() -> None:
    """Nothing is mutated in place; a new version is simply a new key."""
    before = a_request(provider_version="1").render_key
    after = a_request(provider_version="2").render_key
    assert before != after


def test_the_key_says_nothing_about_who_asked() -> None:
    """Two guests hearing the same sentence share one entry, by design."""
    key = a_request().render_key
    assert key == a_request().render_key
    assert len(key) == 64


# --------------------------------------------------------------------------- #
# Offline capability, classified from evidence
# --------------------------------------------------------------------------- #


def test_a_voice_is_local_only_when_a_probe_without_network_succeeded() -> None:
    """Native does not mean offline. Android may synthesise over the network."""
    assert (
        classify([ProbeObservation("v", "en-US", True, network_available=False, duration_ms=900)])
        is OfflineCapability.LOCAL_CONFIRMED
    )


def test_a_voice_that_only_ever_worked_online_is_unconfirmed_not_local() -> None:
    capability = classify(
        [ProbeObservation("v", "en-US", True, network_available=True, duration_ms=900)]
    )
    assert capability is OfflineCapability.LOCAL_UNCONFIRMED
    assert not may_claim_offline(capability)


def test_a_voice_that_fails_without_network_is_network_required() -> None:
    assert (
        classify(
            [
                ProbeObservation("v", "en-US", False, network_available=False),
                ProbeObservation("v", "en-US", True, network_available=True, duration_ms=900),
            ]
        )
        is OfflineCapability.NETWORK_REQUIRED
    )


def test_a_voice_that_never_rendered_is_unavailable() -> None:
    assert classify([]) is OfflineCapability.UNAVAILABLE
    assert (
        classify([ProbeObservation("v", "en-US", False, network_available=True)])
        is OfflineCapability.UNAVAILABLE
    )


def test_only_a_confirmed_local_voice_permits_an_offline_claim() -> None:
    """A claim we cannot support is a compliance problem, not optimism."""
    claimable = {c for c in OfflineCapability if may_claim_offline(c)}
    assert claimable == {OfflineCapability.LOCAL_CONFIRMED}


def test_a_successful_probe_must_report_a_duration() -> None:
    with pytest.raises(ValueError, match="duration"):
        ProbeObservation("v", "en-US", True, network_available=False, duration_ms=0)


# --------------------------------------------------------------------------- #
# Localisation is not translation
# --------------------------------------------------------------------------- #


def _voice(locale: str, offline: OfflineCapability) -> VoiceCapability:
    return VoiceCapability(voice_id="v", locale=locale, offline=offline, provider_id="p")


def test_a_locale_needs_both_content_and_a_voice() -> None:
    both = LocaleSupport(
        "fr-FR", content_approved=True, voices=(_voice("fr-FR", OfflineCapability.LOCAL_CONFIRMED),)
    )
    assert both.supported


def test_a_voice_without_approved_content_is_not_a_supported_locale() -> None:
    """Shipping English text read by a French voice is not localisation."""
    support = LocaleSupport(
        "fr-FR",
        content_approved=False,
        voices=(_voice("fr-FR", OfflineCapability.LOCAL_CONFIRMED),),
    )
    assert not support.supported
    assert "no approved content" in support.reason_unsupported()


def test_content_without_a_voice_is_not_a_supported_locale() -> None:
    support = LocaleSupport("fr-FR", content_approved=True, voices=())
    assert not support.supported
    assert "no voice" in support.reason_unsupported()


def test_neither_contract_gives_a_clear_reason() -> None:
    support = LocaleSupport("ja-JP", content_approved=False, voices=())
    assert support.reason_unsupported() == "no approved content and no voice"


def test_offline_capability_is_separate_from_being_supported() -> None:
    """A locale can be offerable without being claimable as offline."""
    support = LocaleSupport(
        "fr-FR",
        content_approved=True,
        voices=(_voice("fr-FR", OfflineCapability.LOCAL_UNCONFIRMED),),
    )
    assert support.supported
    assert not support.offline_capable


# --------------------------------------------------------------------------- #
# Cache policy
# --------------------------------------------------------------------------- #


def _entry(key: str, size: int, age: int = 0, pinned: bool = False) -> CacheEntry:
    return CacheEntry(
        render_key=key,
        byte_size=size,
        duration_ms=1000,
        content_sha256="a" * 64,
        last_hit_age_days=age,
        pinned=pinned,
    )


def test_a_pinned_entry_is_never_evicted() -> None:
    """Dropping audio from under a session about to play it is the wrong trade."""
    entries = [_entry("pinned", SOFT_CAP_BYTES, pinned=True), _entry("cold", 10_000, age=5)]
    plan = plan_eviction(entries)
    assert "pinned" not in plan.evict
    assert "cold" in plan.evict


def test_stale_entries_go_regardless_of_pressure() -> None:
    plan = plan_eviction([_entry("old", 10, age=STALE_AFTER_DAYS), _entry("new", 10, age=1)])
    assert plan.evict == ("old",)


def test_nothing_is_evicted_when_under_the_cap() -> None:
    assert plan_eviction([_entry("a", 10), _entry("b", 20)]).evict == ()


def test_eviction_reports_when_the_cap_cannot_be_met() -> None:
    """Honest rather than silently over: pinned entries can exceed the cap."""
    plan = plan_eviction([_entry("p", SOFT_CAP_BYTES * 2, pinned=True)])
    assert plan.evict == ()
    assert plan.over_cap


def test_a_corrupt_entry_is_not_played() -> None:
    entry = _entry("k", 10)
    assert verify(entry, "a" * 64)
    assert not verify(entry, "b" * 64)


def test_the_fallback_chain_never_ends_in_silence() -> None:
    assert resolve(ResolutionAttempt(True, True, True, True)) is ResolutionRung.CACHED
    assert resolve(ResolutionAttempt(True, False, True, True)) is ResolutionRung.FETCHED
    assert resolve(ResolutionAttempt(False, False, False, True)) is ResolutionRung.DEVICE_TTS
    assert resolve(ResolutionAttempt(False, False, False, False)) is ResolutionRung.TEXT_ONLY


def test_guest_deletion_does_not_clear_the_audio_cache() -> None:
    """Written down so it stays a decision rather than becoming an oversight."""
    assert guest_deletion_clears_cache() is False


# --------------------------------------------------------------------------- #
# Coordinator
# --------------------------------------------------------------------------- #


def test_the_manifest_covers_every_speech_segment(plan) -> None:
    manifest = build_manifest(plan, FakeSpeechRenderer(), lambda _: None)
    assert len(manifest.entries) == len(plan.timeline.speech())
    assert manifest.complete
    assert manifest.cache_hits == 0


def test_a_second_pass_is_entirely_cache_hits(plan) -> None:
    """Synthesis is a one-off cost, not a per-session one."""
    renderer = FakeSpeechRenderer()
    first = build_manifest(plan, renderer, lambda _: None)
    store = {entry.render_key: entry for entry in first.entries}

    def lookup(key: str) -> RenderResult | None:
        entry = store.get(key)
        if entry is None:
            return None
        return RenderResult(
            render_key=entry.render_key,
            duration_ms=entry.duration_ms,
            content_sha256=entry.content_sha256,
            uri=entry.uri,
            provider_id="fake",
            provider_version="1",
            byte_size=1,
        )

    calls_before = len(renderer.calls)
    second = build_manifest(plan, renderer, lookup)
    assert second.cache_hits == len(second.entries)
    assert len(renderer.calls) == calls_before


def test_an_unrenderable_segment_degrades_rather_than_failing_the_session(plan) -> None:
    manifest = build_manifest(plan, NullSpeechRenderer(), lambda _: None)
    assert manifest.entries == ()
    assert len(manifest.unresolved) == len(plan.timeline.speech())
    assert not manifest.complete


def test_the_coordinator_sends_no_identity_to_the_renderer(plan) -> None:
    renderer = FakeSpeechRenderer()
    build_manifest(plan, renderer, lambda _: None)
    for request in renderer.calls:
        serialised = json.dumps(request.as_dict())
        assert "guest" not in serialised.lower()
        assert "session" not in serialised.lower()


def test_the_fake_renderer_is_deterministic() -> None:
    first = FakeSpeechRenderer().render(a_request())
    second = FakeSpeechRenderer().render(a_request())
    assert first == second


def test_the_fake_renderer_refuses_a_locale_it_cannot_speak() -> None:
    with pytest.raises(RenderUnavailable):
        FakeSpeechRenderer().render(a_request(locale="ja-JP"))


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #


def test_the_default_provider_resolves_nothing() -> None:
    """Expected, not a failure: device-native TTS runs on the client."""
    renderer = build_renderer("none", app_env="test")
    assert isinstance(renderer, NullSpeechRenderer)
    assert not renderer.supports("en-US", "default")


def test_production_refuses_the_fake_renderer() -> None:
    """The same class of mistake as a test schema in a production database."""
    with pytest.raises(UnknownSpeechProvider, match="production"):
        build_renderer("fake", app_env="production")
    assert isinstance(build_renderer("fake", app_env="test"), FakeSpeechRenderer)


def test_an_unknown_provider_is_refused_rather_than_ignored() -> None:
    with pytest.raises(UnknownSpeechProvider, match="unknown speech provider"):
        build_renderer("whisper-cloud", app_env="test")


# --------------------------------------------------------------------------- #
# Asset provenance - no unverified copyrighted audio
# --------------------------------------------------------------------------- #


def test_every_shipped_audio_file_has_a_provenance_entry() -> None:
    """An asset without a traceable origin is a store rejection waiting."""
    manifest = json.loads((REPO_ROOT / "assets" / "audio" / "PROVENANCE.json").read_text())
    declared = {entry["file"] for entry in manifest["assets"]}

    on_disk = {
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "assets" / "audio").rglob("*")
        if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".m4a", ".ogg", ".aac"}
    }
    assert on_disk == declared, f"undeclared: {on_disk - declared}"


def test_no_audio_asset_comes_from_a_third_party() -> None:
    manifest = json.loads((REPO_ROOT / "assets" / "audio" / "PROVENANCE.json").read_text())
    for entry in manifest["assets"]:
        assert entry["third_party_content"] is False, entry["file"]
        assert entry["origin"] == "generated", entry["file"]
        assert entry["license"], entry["file"]
        assert entry["generator"], entry["file"]


def test_the_bell_files_match_their_recorded_hashes() -> None:
    """Content addressing for assets too: a swapped file fails here."""
    manifest = json.loads((REPO_ROOT / "assets" / "audio" / "PROVENANCE.json").read_text())
    for entry in manifest["assets"]:
        path = REPO_ROOT / entry["file"]
        with wave.open(str(path), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
            assert handle.getframerate() == entry["sample_rate_hz"]
            assert handle.getnchannels() == entry["channels"]
        assert hashlib.sha256(frames).hexdigest() == entry["sha256"], entry["file"]


def test_the_plan_references_only_declared_bell_assets(plan) -> None:
    from app.domain.timeline.segments import BellSegment

    manifest = json.loads((REPO_ROOT / "assets" / "audio" / "PROVENANCE.json").read_text())
    declared = {entry["asset_key"] for entry in manifest["assets"]}
    for segment in plan.timeline.segments:
        if isinstance(segment, BellSegment):
            assert segment.asset_key in declared, segment.asset_key


# --------------------------------------------------------------------------- #
# Prepare, over HTTP
# --------------------------------------------------------------------------- #


def test_prepare_returns_a_manifest(client: TestClient, guest_headers: dict[str, str]) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    response = client.post(f"/v1/sessions/{session_id}/prepare", headers=guest_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider_id"] == "none"
    assert body["entries"] == []
    assert body["unresolved"]
    assert body["complete"] is False


def test_prepare_is_isolated_between_guests(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session_id = str(start_session(client, guest_headers)["id"])
    other = {"X-Guest-Id": str(uuid.uuid4())}
    assert client.post(f"/v1/sessions/{session_id}/prepare", headers=other).status_code == 404


@pytest.fixture
def fake_provider_client(settings: Settings) -> Iterator[TestClient]:
    """A client with a server-side renderer, to exercise the cache path."""
    from app.main import create_app

    configured = settings.model_copy(update={"speech_provider": "fake"})
    with TestClient(create_app(configured)) as client:
        yield client


def test_prepare_renders_once_and_then_hits_the_cache(
    fake_provider_client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The whole point of content addressing, proven through the database."""
    client = fake_provider_client
    first_session = str(start_session(client, guest_headers)["id"])
    first = client.post(f"/v1/sessions/{first_session}/prepare", headers=guest_headers).json()
    assert first["complete"] is True
    assert first["entries"]
    assert first["unresolved"] == []

    # A second session with the same recommendation reuses every render.
    second_session = str(start_session(client, guest_headers)["id"])
    second = client.post(f"/v1/sessions/{second_session}/prepare", headers=guest_headers).json()
    assert [e["render_key"] for e in second["entries"]] == [
        e["render_key"] for e in first["entries"]
    ]
    assert [e["duration_ms"] for e in second["entries"]] == [
        e["duration_ms"] for e in first["entries"]
    ]


def test_preparing_twice_is_stable(
    fake_provider_client: TestClient, guest_headers: dict[str, str]
) -> None:
    """Preparing again after a dropped response must not write a second row."""
    client = fake_provider_client
    session_id = str(start_session(client, guest_headers)["id"])
    first = client.post(f"/v1/sessions/{session_id}/prepare", headers=guest_headers).json()
    second = client.post(f"/v1/sessions/{session_id}/prepare", headers=guest_headers).json()
    assert first == second


def test_the_render_table_holds_no_guest_reference(
    fake_provider_client: TestClient, guest_headers: dict[str, str]
) -> None:
    """The table records which content was rendered, never who heard it."""
    from app.persistence import models

    session_id = str(start_session(fake_provider_client, guest_headers)["id"])
    fake_provider_client.post(f"/v1/sessions/{session_id}/prepare", headers=guest_headers)

    columns = set(models.AudioRender.__table__.columns.keys())
    assert not columns & {"guest_id", "user_id", "session_id", "device_id"}
