"""Legal surfaces, logging privacy and the environment model.

SDD_PROGRAM003 sections 16-19, 24, 26 and 27.

The assertions here are mostly about what the documents must *not* say. A policy
can be wrong by claiming a protection that does not exist, and that failure mode
is invisible to every other kind of test.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.legal.documents import (
    WELLNESS_DISCLAIMER_BODY,
    privacy_choices,
    privacy_policy,
    terms_of_use,
)
from app.legal.operator import OperatorIdentity, operator_from_settings
from app.settings import Settings

# Claims the product is not entitled to make. Each one is a real thing services
# assert without basis, and each would be a false statement here.
FORBIDDEN_CLAIMS = (
    "hipaa",
    "gdpr compliant",
    "gdpr certified",
    "iso 27001",
    "soc 2",
    "end-to-end encrypted",
    "medically reviewed",
    "clinically proven",
    "fda",
    "medical record",
    "prescription",
)

OPERATOR = OperatorIdentity(
    brand_name="Test Brand",
    legal_form="individual",
    contact_email="support@example.test",
    support_url="https://example.test/support",
    jurisdiction="England and Wales",
)


def _claims_without_denial(document: str, term: str) -> list[str]:
    """Occurrences of ``term`` that are not preceded by a negation.

    A policy may name HIPAA in order to say it does not comply; that sentence is
    the opposite of the failure this guards against. Only an affirmative use is
    a false claim.
    """
    lowered = " ".join(document.lower().split())
    offenders: list[str] = []
    start = 0
    while (index := lowered.find(term, start)) != -1:
        window = lowered[max(0, index - 60) : index]
        if not any(negation in window for negation in ("not ", "no ", "never ")):
            offenders.append(lowered[max(0, index - 60) : index + len(term) + 20])
        start = index + len(term)
    return offenders


@pytest.mark.parametrize(
    "document",
    [privacy_policy(OPERATOR), terms_of_use(OPERATOR), privacy_choices(OPERATOR)],
    ids=["privacy", "terms", "choices"],
)
def test_no_document_makes_a_claim_it_cannot_support(document: str) -> None:
    for claim in FORBIDDEN_CLAIMS:
        offenders = _claims_without_denial(document, claim)
        assert offenders == [], f"{claim}: {offenders}"


def test_no_document_invents_a_company() -> None:
    """The operator is an individual. A fictitious entity would be a lie in law."""
    for document in (
        privacy_policy(OPERATOR),
        terms_of_use(OPERATOR),
        privacy_choices(OPERATOR),
    ):
        lowered = document.lower()
        for invented in (" ltd", " llc", " inc.", " gmbh", " limited company"):
            assert invented not in lowered, invented

    # The two documents that name an operator must name the real one. The
    # privacy-choices page describes user actions and names no operator at all.
    for document in (privacy_policy(OPERATOR), terms_of_use(OPERATOR)):
        assert "individual developer" in document.lower()


def test_the_privacy_policy_states_what_is_actually_collected() -> None:
    policy = " ".join(privacy_policy(OPERATOR).lower().split())
    for subject in ("check-in", "session", "feedback", "identifier"):
        assert subject in policy
    # And what is not. Stated positively as absences, so a reader does not have
    # to infer them from silence.
    for absent in ("no name.", "no email address.", "no location."):
        assert absent in policy, absent


def test_the_privacy_policy_is_explicit_about_the_identifier() -> None:
    # Strip markup before matching: the emphasis around "not" is presentation.
    policy = " ".join(
        privacy_policy(OPERATOR).lower().replace("<em>", "").replace("</em>", "").split()
    )
    assert "not derived from your device" in policy
    for excluded in ("advertising", "idfa", "imei", "mac address"):
        assert excluded in policy


def test_the_privacy_policy_states_what_is_not_claimed() -> None:
    """The section that makes the rest of the document credible."""
    policy = " ".join(privacy_policy(OPERATOR).lower().split())
    assert "has not had an independent security audit" in policy
    assert "is not hipaa compliant" in policy
    assert "not certified under any privacy framework" in policy


def test_the_terms_cover_the_required_subjects() -> None:
    terms = terms_of_use(OPERATOR).lower()
    for subject in (
        "not a medical device",
        "emergency",
        "do not use this app instead of seeking advice",
        "acceptable use",
        "intellectual property",
        "availability",
        "termination",
        "governing law",
    ):
        assert subject in terms, subject


def test_the_terms_describe_the_ai_boundary() -> None:
    terms = terms_of_use(OPERATOR).lower()
    assert "deterministic rules engine" in terms
    assert "never change which practice" in terms


def test_the_disclaimer_is_short_and_complete() -> None:
    """One surface, shown once. Long enough to be true, short enough to be read."""
    lowered = WELLNESS_DISCLAIMER_BODY.lower()
    assert len(WELLNESS_DISCLAIMER_BODY) < 400
    assert "not a medical service" in lowered
    assert "emergency" in lowered
    assert "professional care" in lowered


def test_the_operator_is_configurable_not_hardcoded() -> None:
    """A later company migration must be configuration, not a rewrite."""
    company = operator_from_settings(
        brand_name="Brand",
        legal_form="Example Company Ltd",
        contact_email="legal@example.test",
        support_url="https://example.test",
        jurisdiction="Ireland",
    )
    assert company.is_individual is False
    assert company.display_operator == "Example Company Ltd"
    assert "Example Company Ltd" in terms_of_use(company)


def test_an_unset_operator_says_so_rather_than_inventing_one() -> None:
    default = Settings().operator
    assert default.brand_name == "not yet published"
    assert default.contact_email == "not yet published"
    assert default.is_individual is True


# --- routes -------------------------------------------------------------------


@pytest.mark.parametrize(
    "route", ["/privacy", "/privacy-choices", "/terms", "/support", "/delete-account"]
)
def test_every_policy_route_is_served(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_the_privacy_choices_page_offers_both_rights(client: TestClient) -> None:
    body = client.get("/privacy-choices").text.lower()
    assert "export your meditation data" in body
    assert "delete your meditation data" in body
    assert "without an account" in body


def test_the_disclaimer_endpoint_serves_one_wording(client: TestClient) -> None:
    body = client.get("/v1/disclaimer").json()
    assert body["title"]
    assert body["body"] == WELLNESS_DISCLAIMER_BODY


# --- environment model --------------------------------------------------------


def test_the_environment_defaults_to_development() -> None:
    """Production must be opted into, never fallen into."""
    assert Settings().app_env == "development"
    assert Settings().is_production is False


def test_production_is_a_configuration_not_a_code_path() -> None:
    """No business logic may branch on the environment.

    A flavour that changes behaviour is a second product to test, so the flag
    exists for configuration - logging, operator metadata - and nothing else.
    """
    import subprocess
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1] / "app"
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", "is_production", str(backend)],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    # Only the settings definition itself may mention it today.
    offenders = [line for line in hits if "settings.py" not in line]
    assert offenders == [], offenders


# --- logging privacy ----------------------------------------------------------


def test_no_sensitive_value_reaches_the_logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Runs the whole slice with logging captured and checks what came out."""
    import uuid as uuid_module

    guest = str(uuid_module.uuid4())
    headers = {"X-Guest-Id": guest}
    check_in = {
        "goal": "overthinking",
        "stress": 8,
        "energy": 5,
        "mental_activity": 9,
        "sleepiness": 2,
        "available_minutes": 10,
        "experience_level": "beginner",
    }
    secret_note = "a private note nobody should see in a log"

    with caplog.at_level(logging.DEBUG):
        receipt = client.post("/v1/check-ins", json=check_in, headers=headers)
        session = client.post(
            "/v1/sessions", json={"check_in_id": receipt.json()["id"]}, headers=headers
        )
        client.post(
            f"/v1/sessions/{session.json()['id']}/feedback",
            json={
                "after_score": 3,
                "helpfulness": 4,
                "completed": True,
                "notes": secret_note,
            },
            headers=headers,
        )
        client.get("/v1/me/export", headers=headers)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_note not in logged, "a free-text note reached the logs"
    assert guest not in logged, "the guest identifier reached the logs"
    client.delete("/v1/me/data", headers=headers)


def _policy_text(client: TestClient) -> str:
    """The policy with its line wrapping removed.

    The source wraps at a sensible column, so a phrase a reader sees as one
    sentence is split across lines in the markup. Asserting on the rendered
    words rather than on the source layout keeps these tests about content.
    """
    return " ".join(client.get("/privacy").text.split()).lower()


def test_the_policy_discloses_what_program004_actually_does(client: TestClient) -> None:
    """Three facts Program004 creates, each stated on the page a user can read.

    A capability the manifests declare and the policy does not mention is the
    kind of gap store review finds, and the kind a user is entitled to be
    annoyed about.
    """
    body = _policy_text(client)

    # Background playback, and what it does not do.
    assert "playing in the background" in body
    assert "collects nothing" in body

    # The Android OS-level TTS behaviour we cannot observe. Disclosed rather
    # than glossed, because "works offline" would be a claim we cannot support.
    assert "text-to-speech" in body
    assert "over the network" in body
    assert "outside this app" in body

    # The headphone rule, stated as the privacy behaviour it is.
    assert "headphones disconnect" in body


def test_the_policy_still_denies_recording_anything(client: TestClient) -> None:
    """Speaking is not listening, and the policy has to be unambiguous."""
    body = _policy_text(client)
    assert "the app speaks; it never listens." in body
    assert "no camera or microphone access" in body


def test_the_policy_says_no_identity_reaches_a_speech_service(
    client: TestClient,
) -> None:
    """The claim the render-request check enforces, written where users see it."""
    body = _policy_text(client)
    assert "no identifier, no session, no history and nothing you have typed" in body
    assert "speech service" in body
