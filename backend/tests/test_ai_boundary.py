"""AI boundary tests.

Two claims are checked here, both of which the SDD states as invariants:
the deterministic core runs with no credential, and a provider cannot change
the practice envelope.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.guard import EnvelopeViolation, apply_personalization, check_envelope
from app.ai.providers.base import PersonalizationRequest, PersonalizationResult
from app.ai.providers.null import NullAIProvider, NullTTSProvider
from app.ai.providers.registry import (
    UnknownProviderError,
    build_ai_provider,
    build_safety_router,
    build_tts_provider,
)
from app.ai.safety.router import NoopSafetyRouter, SafetyAction, SafetyRouter
from app.domain.recommendation.engine import RecommendationEngine
from app.domain.state.models import CheckIn
from app.main import create_app
from app.settings import Settings

from .conftest import KNOWLEDGE_DIR

REQUEST = PersonalizationRequest(
    practice_id="body_awareness",
    duration_minutes=10,
    guidance_density=0.65,
    stage_prompts=("one", "two", "three"),
)


def result(**overrides: object) -> PersonalizationResult:
    base: dict[str, object] = {
        "provider_id": "test",
        "practice_id": REQUEST.practice_id,
        "duration_minutes": REQUEST.duration_minutes,
        "guidance_density": REQUEST.guidance_density,
        "stage_prompts": REQUEST.stage_prompts,
    }
    base.update(overrides)
    return PersonalizationResult(**base)  # type: ignore[arg-type]


def test_no_credential_selects_the_null_provider() -> None:
    settings = Settings(ai_provider="null", ai_api_key=None, knowledge_dir=KNOWLEDGE_DIR)
    assert settings.ai_enabled is False
    assert build_ai_provider(settings).provider_id == "null"
    assert build_tts_provider(settings).provider_id == "null"
    assert isinstance(build_safety_router(settings), SafetyRouter)


def test_named_provider_without_a_key_still_falls_back_to_null() -> None:
    settings = Settings(ai_provider="openai", ai_api_key=None, knowledge_dir=KNOWLEDGE_DIR)
    assert build_ai_provider(settings).provider_id == "null"


def test_unimplemented_provider_with_a_key_fails_loudly() -> None:
    settings = Settings(ai_provider="openai", ai_api_key="x", knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(UnknownProviderError):
        build_ai_provider(settings)


def test_app_boots_and_recommends_with_no_ai_key(settings: Settings) -> None:
    """SDD section 16: the API must boot and answer without any AI API key."""
    stripped = settings.model_copy(update={"ai_provider": "null", "ai_api_key": None})
    with TestClient(create_app(stripped)) as client:
        assert client.get("/healthz").json()["ai_provider_configured"] is False
        response = client.post(
            "/v1/recommendations",
            json={
                "goal": "sleep",
                "stress": 4,
                "energy": 3,
                "mental_activity": 8,
                "sleepiness": 7,
                "available_minutes": 15,
                "experience_level": "beginner",
            },
        )
        assert response.status_code == 200
        assert response.json()["practice_id"] == "body_awareness"


def test_null_provider_returns_wording_unchanged() -> None:
    outcome = NullAIProvider().personalize(REQUEST)
    assert outcome.stage_prompts == REQUEST.stage_prompts
    assert check_envelope(REQUEST, outcome) == ()


def test_null_tts_produces_no_audio() -> None:
    from app.ai.providers.base import SpeechRequest

    speech = NullTTSProvider().synthesize(SpeechRequest(text="hello"))
    assert speech.audio is None


def test_personalized_wording_is_accepted_when_the_envelope_holds() -> None:
    # Program005 policy 1: the provider may restate the first stage only. A
    # rewrite confined to it, keeping the envelope, is accepted as a whole.
    outcome = apply_personalization(REQUEST, result(stage_prompts=("a", "two", "three")))
    assert outcome.personalized is True
    assert outcome.stage_prompts == ("a", "two", "three")
    assert outcome.violations == ()


def test_rewriting_a_later_stage_is_rejected_as_a_whole() -> None:
    # Before Program005 this was accepted: the envelope held. It is now a
    # wording violation, and the deterministic text survives for every stage,
    # including the first one the provider was allowed to change.
    outcome = apply_personalization(REQUEST, result(stage_prompts=("a", "b", "c")))
    assert outcome.personalized is False
    assert outcome.violations == ("protected_stage[1]", "protected_stage[2]")
    assert outcome.stage_prompts == REQUEST.stage_prompts


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"practice_id": "kindness"}, "practice_id"),
        ({"duration_minutes": 20}, "duration_minutes"),
        ({"guidance_density": 0.2}, "guidance_density"),
        ({"stage_prompts": ("only one",)}, "stage_count"),
    ],
)
def test_envelope_change_is_rejected_not_silently_accepted(
    override: dict[str, object], field: str
) -> None:
    outcome = apply_personalization(REQUEST, result(**override))
    assert outcome.personalized is False
    assert field in outcome.violations
    # The deterministic wording survives.
    assert outcome.stage_prompts == REQUEST.stage_prompts
    with pytest.raises(EnvelopeViolation):
        apply_personalization(REQUEST, result(**override), strict=True)


def test_safety_router_allows_everything_and_claims_nothing() -> None:
    decision = NoopSafetyRouter().classify("any text at all")
    assert decision.action is SafetyAction.ALLOW
    assert decision.allows_generation is True
    assert decision.router_id == "noop"
    assert "no classification" in decision.detail


def test_recommendation_engine_makes_no_network_or_database_call(
    engine: RecommendationEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deterministic path must not reach a socket."""
    import socket

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the recommendation engine opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    result_ = engine.recommend(
        CheckIn.model_validate(
            {
                "goal": "focus",
                "stress": 3,
                "energy": 6,
                "mental_activity": 4,
                "sleepiness": 2,
                "available_minutes": 5,
                "experience_level": "intermediate",
            }
        )
    )
    assert result_.practice_id == "breath_awareness"
