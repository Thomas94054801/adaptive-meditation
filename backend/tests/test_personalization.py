"""Program005 Slice A - familiarity, presentation variants, provenance, AI path.

PERS-01..13 from the SDD. Everything runs under the production configuration
(null provider, no key) unless a test injects a stub through the dependency
override, and every stub is named for the failure it stands in for.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.ai.providers.base import (
    FORBIDDEN_REQUEST_FIELDS,
    PersonalizationRequest,
    PersonalizationResult,
)
from app.api.deps import get_ai_provider
from app.domain.personalization import (
    EVIDENCE_CAP,
    POLICY_VERSION,
    Familiarity,
    FamiliarityTier,
    PresentationVariant,
    personalize,
    variant_definition,
)
from app.domain.practice.catalog import (
    KnowledgeValidationError,
    get_catalog,
    validate_returning_template,
)
from app.domain.recommendation.engine import Recommendation
from app.domain.timeline.definition import DEFINITION_SCHEMA_VERSION, ContentSource, definition_for
from app.domain.timeline.planner_v2 import build_plan
from app.domain.timeline.segments import SilenceSegment, SpeechSegment, segment_as_dict
from app.persistence import models
from app.persistence.database import Database
from app.persistence.repositories import SessionRepository
from app.persistence.seed import TARGET_PRACTICE, seed_history
from app.settings import Settings

from .conftest import KNOWLEDGE_DIR

FIXTURE = Path(__file__).parent / "fixtures" / "definition_baseline.v1.json"

CHECK_IN = {
    "goal": "overthinking",
    "stress": 8,
    "energy": 5,
    "mental_activity": 9,
    "sleepiness": 2,
    "available_minutes": 10,
    "experience_level": "beginner",
}


def create_session(client: TestClient, headers: dict[str, str], **extra: object) -> dict[str, Any]:
    created = client.post("/v1/check-ins", json=CHECK_IN, headers=headers)
    assert created.status_code == 201, created.text
    response = client.post(
        "/v1/sessions", json={"check_in_id": created.json()["id"], **extra}, headers=headers
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def complete(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/v1/sessions/{session_id}/feedback",
        json={"after_score": 4, "helpfulness": 4, "completed": True},
    )
    assert response.status_code == 204, response.text


def abandon(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/v1/sessions/{session_id}/feedback",
        json={"after_score": 2, "helpfulness": 2, "completed": False},
    )
    assert response.status_code == 204, response.text


def first_speech(session: dict[str, Any]) -> str:
    segments = session["plan_v2"]["segments"]
    return next(s["text"] for s in segments if s["kind"] == "speech")


def speech_texts(session: dict[str, Any]) -> list[str]:
    return [s["text"] for s in session["plan_v2"]["segments"] if s["kind"] == "speech"]


@pytest.fixture
def catalog():
    return get_catalog(KNOWLEDGE_DIR)


@pytest.fixture
def database(settings: Settings) -> Database:
    return Database(settings)


# --------------------------------------------------------------------------- #
# PERS-01 / 02 / 07 / 10 - the visible effect under production configuration
# --------------------------------------------------------------------------- #


def test_pers01_first_time_guest_gets_the_canonical_opening(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = create_session(client, guest_headers)
    p = session["personalization"]
    assert p["familiarity_tier"] == "new"
    assert p["evidence_count"] == 0
    assert p["evidence_capped"] is False
    assert p["presentation_variant"] == "canonical"
    assert p["personalized"] is False
    assert p["provider_id"] == "null"
    assert p["ai_attempted"] is False
    assert p["ai_accepted"] is False
    assert p["fallback_reason"] == "provider_absent"
    assert p["reason"] == "first_time_with_this_practice"
    assert p["personalization_policy_version"] == POLICY_VERSION
    assert not first_speech(session).startswith("Welcome back")


def test_pers02_returning_guest_hears_the_returning_opening(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    first = create_session(client, guest_headers)
    complete(client, first["id"])
    second = create_session(client, guest_headers)

    p = second["personalization"]
    assert p["familiarity_tier"] == "returning"
    assert p["evidence_count"] == 1
    assert p["presentation_variant"] == "returning"
    assert p["personalized"] is True
    assert p["provider_id"] == "null"
    assert p["ai_attempted"] is False
    assert p["reason"] == "returning_to_this_practice"
    assert first_speech(second).startswith("Welcome back.")
    # A different definition, because the words differ - nothing else.
    assert second["plan_v2"]["definition_id"] != first["plan_v2"]["definition_id"]


def test_pers10_null_provider_is_the_production_path(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    assert client.app.state.settings.ai_provider == "null"
    assert client.app.state.settings.ai_api_key is None
    assert client.app.state.ai_provider.provider_id == "null"
    session = create_session(client, guest_headers)
    assert session["personalization"]["fallback_reason"] == "provider_absent"
    assert session["plan_v2"]["segments"]  # a valid, playable plan


def test_pers07_provenance_is_frozen_returned_and_exported(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    session = create_session(client, guest_headers)
    read = client.get(f"/v1/sessions/{session['id']}", headers=guest_headers)
    assert read.status_code == 200
    assert read.json()["personalization"] == session["personalization"]

    export = client.get("/v1/me/export", headers=guest_headers)
    assert export.status_code == 200
    exported = [s for s in export.json()["sessions"] if s["id"] == session["id"]]
    assert exported and exported[0]["personalization"] == session["personalization"]
    assert set(session["personalization"]) == {
        "schema_version",
        "personalization_policy_version",
        "familiarity_tier",
        "evidence_count",
        "evidence_capped",
        "presentation_variant",
        "adaptive_wording_enabled",
        "personalized",
        "provider_id",
        "ai_attempted",
        "ai_accepted",
        "fallback_reason",
        "reason",
    }


def test_pers08_history_growth_does_not_rewrite_an_old_session(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    first = create_session(client, guest_headers)
    before = client.get(f"/v1/sessions/{first['id']}", headers=guest_headers).content
    complete(client, first["id"])
    for _ in range(2):
        complete(client, create_session(client, guest_headers)["id"])
    # The preference flipping later changes nothing either.
    create_session(client, guest_headers, adaptive_wording=False)
    after = client.get(f"/v1/sessions/{first['id']}", headers=guest_headers).content
    # status/completed_at moved because the session was completed; everything
    # personalization-related is byte-identical.
    before_json, after_json = json.loads(before), json.loads(after)
    for key in ("personalization", "plan_v2", "plan", "recommendation"):
        assert before_json[key] == after_json[key], key
    assert after_json["personalization"]["familiarity_tier"] == "new"


# --------------------------------------------------------------------------- #
# PERS-03 / 04 / 05 - the envelope and the plan structure never move
# --------------------------------------------------------------------------- #


def test_pers03_04_practice_and_duration_identical_across_tiers_and_preference(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    new = create_session(client, guest_headers)
    complete(client, new["id"])
    returning = create_session(client, guest_headers)
    off = create_session(client, guest_headers, adaptive_wording=False)

    for session in (returning, off):
        assert session["recommendation"] == new["recommendation"]
        assert session["plan_v2"]["target_total_ms"] == new["plan_v2"]["target_total_ms"]
        assert session["plan_v2"]["practice_id"] == new["plan_v2"]["practice_id"]
        assert session["plan_v2"]["guidance_density"] == new["plan_v2"]["guidance_density"]
    assert off["personalization"]["presentation_variant"] == "canonical"
    assert off["plan_v2"]["definition_id"] == new["plan_v2"]["definition_id"]


def _structure(plan) -> list[tuple[object, ...]]:
    out: list[tuple[object, ...]] = []
    for segment in plan.timeline.segments:
        row: tuple[object, ...] = (segment.kind.value, segment.id)
        if isinstance(segment, SilenceSegment):
            row += ("silence", segment.min_ms <= segment.target_ms)
        elif isinstance(segment, SpeechSegment):
            row += ("speech",)
        else:
            row += tuple(sorted(segment_as_dict(segment).items()))
        out.append(row)
    return out


def test_pers05_seven_practices_five_durations_only_the_opening_differs(catalog) -> None:
    """35 plan pairs: same stages, same order, same bells, same target; every
    non-first speech byte-equal; the opening's silence floor never lowered."""
    compared = 0
    for practice_id, protocol in sorted(catalog.protocols_by_practice.items()):
        canonical = definition_for(catalog, practice_id)
        returning = variant_definition(catalog, practice_id, PresentationVariant.RETURNING)
        assert returning.definition_id != canonical.definition_id
        for minutes in protocol.duration_supported:
            rec = Recommendation(
                practice_id=practice_id,
                duration_minutes=minutes,
                guidance_density=protocol.guidance_density_range[0],
                reason_codes=(),
            )
            a = build_plan(rec, canonical, protocol, None)
            b = build_plan(rec, returning, protocol, None)
            assert a.target_total_ms == b.target_total_ms
            assert _structure(a) == _structure(b)
            speech_a = [s for s in a.timeline.segments if isinstance(s, SpeechSegment)]
            speech_b = [s for s in b.timeline.segments if isinstance(s, SpeechSegment)]
            assert speech_a[0].text != speech_b[0].text
            assert speech_b[0].text.startswith("Welcome back.")
            assert [s.text for s in speech_a[1:]] == [s.text for s in speech_b[1:]]
            silences_a = [s for s in a.timeline.segments if isinstance(s, SilenceSegment)]
            silences_b = [s for s in b.timeline.segments if isinstance(s, SilenceSegment)]
            assert len(silences_a) == len(silences_b)
            # Opening stage: shorter speech means at least as much silence and
            # a floor at least as high. Every later stage: identical timing.
            assert silences_b[0].target_ms >= silences_a[0].target_ms
            assert silences_b[0].min_ms >= silences_a[0].min_ms
            assert [segment_as_dict(s) for s in silences_a[1:]] == [
                segment_as_dict(s) for s in silences_b[1:]
            ]
            compared += 1
    assert compared == 35


# --------------------------------------------------------------------------- #
# PERS-06 - the count reproduces the tier from stored rows
# --------------------------------------------------------------------------- #


def test_pers06_count_over_seeded_history(database: Database) -> None:
    zero, one, many, other = (uuid.uuid4() for _ in range(4))
    with database.session() as session:
        seed_history(session, guest_id=zero, rows=300, matches=0, abandoned_target=40)
        seed_history(session, guest_id=one, rows=300, matches=1, abandoned_target=40)
        seed_history(session, guest_id=many, rows=600, matches=150, abandoned_target=50)
        seed_history(session, guest_id=other, rows=50, matches=50)
    with database.session() as session:
        repo = SessionRepository(session)
        assert repo.completed_count(zero, TARGET_PRACTICE, cap=EVIDENCE_CAP) == 0
        assert repo.completed_count(one, TARGET_PRACTICE, cap=EVIDENCE_CAP) == 1
        assert repo.completed_count(many, TARGET_PRACTICE, cap=EVIDENCE_CAP) == EVIDENCE_CAP
        # Other guests and other practices are not this guest's evidence.
        assert repo.completed_count(zero, "kindness", cap=EVIDENCE_CAP) > 0
        assert repo.completed_count(uuid.uuid4(), TARGET_PRACTICE, cap=EVIDENCE_CAP) == 0
        # The cap is a cap: a smaller one saturates sooner, the raw truth is 150.
        assert repo.completed_count(many, TARGET_PRACTICE, cap=10) == 10
        assert repo.completed_count(many, TARGET_PRACTICE, cap=1_000) == 150

    assert Familiarity.from_count(0).tier is FamiliarityTier.NEW
    assert Familiarity.from_count(1).tier is FamiliarityTier.RETURNING
    saturated = Familiarity.from_count(EVIDENCE_CAP)
    assert saturated.evidence_capped is True and saturated.evidence_count == EVIDENCE_CAP
    assert Familiarity.from_count(99).evidence_capped is False
    assert Familiarity.unknown().history_available is False


def test_pers06_abandoned_sessions_do_not_count_over_http(
    client: TestClient, guest_headers: dict[str, str]
) -> None:
    abandon(client, create_session(client, guest_headers)["id"])
    session = create_session(client, guest_headers)
    assert session["personalization"]["familiarity_tier"] == "new"
    assert session["personalization"]["evidence_count"] == 0


def test_the_familiarity_index_exists_after_migration(settings: Settings) -> None:
    engine = sa.create_engine(
        settings.database_url,
        connect_args=(
            {"options": f"-csearch_path={settings.database_schema}"}
            if settings.database_schema and settings.database_url.startswith("postgresql")
            else {}
        ),
    )
    try:
        names = {index["name"] for index in sa.inspect(engine).get_indexes("sessions")}
    finally:
        engine.dispose()
    assert "ix_sessions_familiarity" in names


# --------------------------------------------------------------------------- #
# PERS-09 / 11 / 12 - the provider path, with stubs named for their failure
# --------------------------------------------------------------------------- #


class SpyProvider:
    provider_id = "spy"

    def __init__(self) -> None:
        self.requests: list[PersonalizationRequest] = []

    def personalize(self, request: PersonalizationRequest) -> PersonalizationResult:
        self.requests.append(request)
        return PersonalizationResult(
            provider_id=self.provider_id,
            practice_id=request.practice_id,
            duration_minutes=request.duration_minutes,
            guidance_density=request.guidance_density,
            stage_prompts=request.stage_prompts,
        )


class RewritingProvider(SpyProvider):
    """Rewrites the opening only, keeping the placeholder and the envelope."""

    provider_id = "rewriting"

    def personalize(self, request: PersonalizationRequest) -> PersonalizationResult:
        self.requests.append(request)
        prompts = (
            "Settle in for ${duration_minutes} minutes, in your own time.",
            *request.stage_prompts[1:],
        )
        return dataclasses.replace(super().personalize(request), stage_prompts=prompts)


class MutatingProvider(SpyProvider):
    provider_id = "mutating"

    def __init__(self, **overrides: object) -> None:
        super().__init__()
        self.overrides = overrides

    def personalize(self, request: PersonalizationRequest) -> PersonalizationResult:
        base = super().personalize(request)
        values = {k: v(request) if callable(v) else v for k, v in self.overrides.items()}
        return dataclasses.replace(base, **values)  # type: ignore[arg-type]


class RaisingProvider(SpyProvider):
    provider_id = "raising"

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def personalize(self, request: PersonalizationRequest) -> PersonalizationResult:
        self.requests.append(request)
        raise self.error


class GarbageProvider(SpyProvider):
    provider_id = "garbage"

    def personalize(self, request: PersonalizationRequest):  # type: ignore[override]
        self.requests.append(request)
        return {"stage_prompts": list(request.stage_prompts)}


@pytest.fixture
def inject(client: TestClient):
    def _inject(provider: object) -> None:
        client.app.dependency_overrides[get_ai_provider] = lambda: provider

    yield _inject
    client.app.dependency_overrides.pop(get_ai_provider, None)


def test_pers09_adaptive_wording_off_never_calls_the_provider(
    client: TestClient, guest_headers: dict[str, str], inject
) -> None:
    spy = SpyProvider()
    inject(spy)
    complete(client, create_session(client, guest_headers)["id"])
    spy.requests.clear()
    session = create_session(client, guest_headers, adaptive_wording=False)
    assert spy.requests == []
    p = session["personalization"]
    assert p["adaptive_wording_enabled"] is False
    assert p["presentation_variant"] == "canonical"
    assert p["personalized"] is False
    assert p["fallback_reason"] == "adaptive_wording_disabled"
    assert p["reason"] == "adaptive_wording_off"
    assert not first_speech(session).startswith("Welcome back")


def test_the_request_carries_no_identity_and_no_history(
    client: TestClient, guest_headers: dict[str, str], inject
) -> None:
    spy = SpyProvider()
    inject(spy)
    complete(client, create_session(client, guest_headers)["id"])
    create_session(client, guest_headers)
    assert spy.requests, "the provider path must be reachable"
    serialised = dataclasses.asdict(spy.requests[-1])
    assert set(serialised) == {
        "practice_id",
        "duration_minutes",
        "guidance_density",
        "stage_prompts",
        "presentation_variant",
    }
    assert not (set(serialised) & FORBIDDEN_REQUEST_FIELDS)
    text = json.dumps(serialised)
    assert guest_headers["X-Guest-Id"] not in text
    assert serialised["presentation_variant"] == "returning"


def test_an_accepted_rewrite_is_frozen_as_generated_content(
    client: TestClient, guest_headers: dict[str, str], inject, database: Database
) -> None:
    inject(RewritingProvider())
    session = create_session(client, guest_headers)
    p = session["personalization"]
    assert p["ai_attempted"] is True and p["ai_accepted"] is True
    assert p["personalized"] is True and p["fallback_reason"] is None
    assert first_speech(session).startswith("Settle in for 10 minutes, in your own time.")
    with database.session() as db:
        row = db.get(models.SessionDefinitionRow, session["plan_v2"]["definition_id"])
        assert row is not None and row.source == ContentSource.GENERATED.value


@pytest.mark.parametrize(
    ("overrides", "fallback"),
    [
        ({"practice_id": "kindness"}, "envelope_violation"),
        ({"duration_minutes": 20}, "envelope_violation"),
        ({"stage_prompts": lambda r: r.stage_prompts[:-1]}, "envelope_violation"),
        # Wording the guard refuses.
        ({"stage_prompts": lambda r: (*r.stage_prompts[:-1], "changed")}, "wording_rejected"),
        (
            {"stage_prompts": lambda r: ("no placeholder here", *r.stage_prompts[1:])},
            "wording_rejected",
        ),
        ({"stage_prompts": lambda r: ("   ", *r.stage_prompts[1:])}, "wording_rejected"),
        (
            {"stage_prompts": lambda r: ("x" * 601 + " ${duration_minutes}", *r.stage_prompts[1:])},
            "wording_rejected",
        ),
        (
            {
                "stage_prompts": lambda r: (
                    "This treatment takes ${duration_minutes} minutes.",
                    *r.stage_prompts[1:],
                )
            },
            "wording_rejected",
        ),
        ({"stage_prompts": lambda r: (42, *r.stage_prompts[1:])}, "wording_rejected"),
    ],
)
def test_pers11_violations_keep_the_deterministic_wording(
    client: TestClient,
    guest_headers: dict[str, str],
    inject,
    database: Database,
    overrides: dict[str, object],
    fallback: str,
) -> None:
    def generated_rows() -> int:
        with database.session() as db:
            return int(
                db.execute(
                    sa.select(sa.func.count())
                    .select_from(models.SessionDefinitionRow)
                    .where(models.SessionDefinitionRow.source == ContentSource.GENERATED.value)
                ).scalar_one()
            )

    generated_before = generated_rows()
    inject(MutatingProvider(**overrides))
    session = create_session(client, guest_headers)
    p = session["personalization"]
    assert p["ai_attempted"] is True
    assert p["ai_accepted"] is False
    assert p["fallback_reason"] == fallback
    assert p["personalized"] is False
    # The engine's decision for this check-in, whatever the provider claimed.
    control = create_session(client, guest_headers, adaptive_wording=False)
    assert session["recommendation"] == control["recommendation"]
    canonical = definition_for(get_catalog(KNOWLEDGE_DIR), session["recommendation"]["practice_id"])
    assert session["plan_v2"]["definition_id"] == canonical.definition_id
    assert (
        generated_rows() == generated_before
    ), "a rejected result must never reach a definition row"


@pytest.mark.parametrize(
    ("provider", "fallback"),
    [
        (RaisingProvider(RuntimeError("boom")), "provider_error"),
        (RaisingProvider(TimeoutError("slow")), "provider_timeout"),
        (GarbageProvider(), "malformed_output"),
    ],
)
def test_pers12_provider_failure_cannot_prevent_meditation(
    client: TestClient, guest_headers: dict[str, str], inject, provider: SpyProvider, fallback: str
) -> None:
    inject(provider)
    session = create_session(client, guest_headers)
    assert len(provider.requests) == 1, "exactly one attempt, no retry"
    p = session["personalization"]
    assert p["ai_attempted"] is True and p["ai_accepted"] is False
    assert p["fallback_reason"] == fallback
    assert session["plan_v2"]["segments"]


# --------------------------------------------------------------------------- #
# PERS-13 - the baseline fixture: nothing the old code produced has drifted
# --------------------------------------------------------------------------- #


def test_pers13_schema1_baseline_round_trips_without_drift(catalog) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["generated_at_commit"] == "367736a2d4269ac1a951d82e5fb0233d1d59238f"
    assert fixture["definition_schema_version"] == DEFINITION_SCHEMA_VERSION == 1
    assert set(fixture["practices"]) == set(catalog.practices)
    plans_checked = 0
    for practice_id, expected in fixture["practices"].items():
        definition = definition_for(catalog, practice_id)
        canonical = definition.canonical()
        assert canonical == expected["canonical_json"], practice_id
        assert hashlib.sha256(canonical.encode()).hexdigest() == expected["canonical_sha256"]
        assert definition.definition_id == expected["definition_id"], practice_id
        protocol = catalog.protocol_for(practice_id)
        for minutes, plan_expected in expected["plans"].items():
            rec = Recommendation(
                practice_id=practice_id,
                duration_minutes=int(minutes),
                guidance_density=expected["guidance_density"],
                reason_codes=(),
            )
            plan = build_plan(rec, definition, protocol, None)
            assert plan.plan_hash == plan_expected["plan_hash"], (practice_id, minutes)
            assert plan.target_total_ms == plan_expected["target_total_ms"]
            assert [s.id for s in plan.timeline.segments] == plan_expected["segment_ids"]
            plans_checked += 1
    assert plans_checked == 35


# --------------------------------------------------------------------------- #
# Knowledge validation and the pure pipeline
# --------------------------------------------------------------------------- #


def test_every_practice_declares_one_returning_opening_on_its_first_stage(catalog) -> None:
    for practice_id, protocol in catalog.protocols_by_practice.items():
        assert protocol.stages[0].returning_prompt_template, practice_id
        assert all(s.returning_prompt_template is None for s in protocol.stages[1:]), practice_id


@pytest.mark.parametrize(
    ("returning", "message"),
    [
        (
            "Welcome back for ${duration_minutes} minutes and rather more words than before",
            "words",
        ),
        ("Welcome back, settle in.", "placeholders"),
        ("Welcome back. This therapy takes ${duration_minutes} minutes.", "therapy"),
    ],
)
def test_returning_template_rules_are_enforced_at_load(returning: str, message: str) -> None:
    canonical = "Settle for ${duration_minutes} minutes. Let the body be still."
    with pytest.raises((KnowledgeValidationError, ValueError), match=message):
        validate_returning_template(canonical, returning, where="test")


def test_personalize_without_a_returning_template_stays_canonical_and_says_so(catalog) -> None:
    """A practice whose first stage has no variant is not "returning" in name only."""
    protocol = catalog.protocol_for(TARGET_PRACTICE)
    stripped = protocol.model_copy(
        update={
            "stages": (
                protocol.stages[0].model_copy(update={"returning_prompt_template": None}),
                *protocol.stages[1:],
            )
        }
    )
    reduced = dataclasses.replace(
        catalog, protocols_by_practice={**catalog.protocols_by_practice, TARGET_PRACTICE: stripped}
    )
    result = personalize(
        catalog=reduced,
        practice_id=TARGET_PRACTICE,
        duration_minutes=10,
        guidance_density=0.5,
        familiarity=Familiarity.from_count(3),
        adaptive_wording=True,
        provider=None,
    )
    assert result.provenance.presentation_variant is PresentationVariant.CANONICAL
    assert result.provenance.personalized is False
    assert result.provenance.familiarity.tier is FamiliarityTier.RETURNING
