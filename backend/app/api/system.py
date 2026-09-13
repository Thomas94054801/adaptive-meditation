"""Health, disclaimer and public policy routes.

``/healthz`` reports what the process can prove and answers without an AI
credential or a reachable database.

The policy routes describe what the service actually does. Where a capability is
absent they say so, because a policy that is silent about a subject reads as if
the thing happens.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.api.deps import CatalogDep, EngineDep, SettingsDep
from app.api.v1.schemas import DisclaimerResponse, HealthResponse
from app.domain.recommendation.versions import ENGINE_VERSION
from app.legal.documents import (
    WELLNESS_DISCLAIMER_BODY,
    WELLNESS_DISCLAIMER_TITLE,
    privacy_choices,
    privacy_policy,
    terms_of_use,
)
from app.settings import Settings

router = APIRouter(tags=["system"])

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 44rem;
         margin: 0 auto; padding: 2rem 1.25rem 4rem; line-height: 1.65; }}
  h1 {{ font-size: 1.75rem; margin-bottom: .25rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  .meta {{ opacity: .7; font-size: .9rem; margin-top: 0; }}
  code {{ font-size: .9em; }}
  nav {{ margin-top: 3rem; font-size: .9rem; opacity: .8; }}
  nav a {{ margin-right: 1rem; }}
</style></head>
<body>
<h1>{title}</h1>
{body}
<nav><a href="/privacy">Privacy</a><a href="/privacy-choices">Your privacy choices</a>
<a href="/terms">Terms</a><a href="/support">Support</a>
<a href="/delete-account">Deleting your data</a></nav>
</body></html>
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(title=title, body=body))


@router.get("/healthz", operation_id="healthz", response_model=HealthResponse)
def healthz(settings: SettingsDep, catalog: CatalogDep, engine: EngineDep) -> HealthResponse:
    """Reports the versions actually serving traffic.

    Program001 reported a single ``rules_version`` taken from a module constant,
    which kept saying "1" after the engine moved to rule set 2. Reading the
    values off the live engine and catalog means the endpoint cannot drift from
    what is running.
    """
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        api_version=settings.api_version,
        engine_version=ENGINE_VERSION,
        rule_set_version=engine.rule_set.version,
        knowledge_version=catalog.knowledge_version,
        practices_loaded=len(catalog.practices),
        protocols_loaded=len(catalog.protocols_by_practice),
        ai_provider_configured=settings.ai_enabled,
    )


@router.get(
    "/v1/disclaimer",
    operation_id="wellnessDisclaimer",
    response_model=DisclaimerResponse,
    tags=["v1"],
    summary="The one wellness disclaimer surface",
)
def disclaimer() -> DisclaimerResponse:
    """Served to the client so the wording lives in one place.

    One surface, shown once. A warning repeated on every screen stops being read,
    which makes the product worse without making it safer.
    """
    return DisclaimerResponse(title=WELLNESS_DISCLAIMER_TITLE, body=WELLNESS_DISCLAIMER_BODY)


@router.get("/privacy", operation_id="privacyPolicy", response_class=HTMLResponse)
def privacy(settings: SettingsDep) -> HTMLResponse:
    return _page("Privacy Policy", privacy_policy(settings.operator))


@router.get("/privacy-choices", operation_id="privacyChoices", response_class=HTMLResponse)
def privacy_choices_page(settings: SettingsDep) -> HTMLResponse:
    """The URL Apple's User Privacy Choices field points at."""
    return _page("Your privacy choices", privacy_choices(settings.operator))


@router.get("/terms", operation_id="termsOfUse", response_class=HTMLResponse)
def terms(settings: SettingsDep) -> HTMLResponse:
    return _page("Terms of Use", terms_of_use(settings.operator))


@router.get("/support", operation_id="support", response_class=HTMLResponse)
def support(settings: SettingsDep) -> HTMLResponse:
    return _page("Support", _support_body(settings))


@router.get("/delete-account", operation_id="deleteAccountInfo", response_class=HTMLResponse)
def delete_account(settings: SettingsDep) -> HTMLResponse:
    return _page("Deleting your data", _delete_body(settings))


def _support_body(settings: Settings) -> str:
    return f"""
<p>This app is maintained by {settings.operator.display_operator}. Support is
email only, and replies are not immediate.</p>
<p>Contact: <strong>{settings.operator.contact_email}</strong></p>
<h2>Reporting a problem with a session</h2>
<p>The session identifier shown at the end of a session is enough to locate it.
Please do not include health information you would rather not share - it is not
needed to investigate a technical problem.</p>
<h2>Deleting or exporting your data</h2>
<p>Both are available inside the app without contacting support. See
<a href="/privacy-choices">your privacy choices</a>.</p>
<h2>What support cannot do</h2>
<p>Support is technical. It cannot give medical, psychological or crisis advice.
If you are in crisis, contact your local emergency number or a crisis line.</p>
"""


def _delete_body(settings: Settings) -> str:
    return f"""
<p>There are no accounts in this version, so there is no account to close. Your
data is stored against a random identifier generated on your device, which is
not linked to your name, your email or anything about your device.</p>
<h2>Deleting everything</h2>
<p>In the app, open <strong>Your sessions</strong> and choose
<strong>Delete my meditation data</strong>. That permanently removes your
check-ins, sessions, feedback and any experiment assignment from the service.
There is no waiting period, nothing is kept back, and your device then starts
with a new identifier.</p>
<h2>Taking a copy first</h2>
<p>The same screen offers <strong>Export my meditation data</strong>, which
returns everything stored against your identifier as JSON.</p>
<h2>If you uninstall without deleting</h2>
<p>The identifier is removed from your device, but the data stays on the service
with no remaining way to connect it to you. Delete it from inside the app first
if you want it gone.</p>
<h2>If accounts are added later</h2>
<p>In-app account deletion will ship in the same release as account creation,
not after it.</p>
<p>Questions: <strong>{settings.operator.contact_email}</strong></p>
"""
