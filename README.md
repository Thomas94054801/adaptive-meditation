# Adaptive Meditation

US-first AI adaptive mindfulness and meditation platform.

## Product thesis

The product translates a source-grounded contemplative practice system into accessible, non-sectarian Western wellness language. The user starts with a current-state check-in; the system selects a suitable practice protocol; AI may personalize wording and voice but does not own the practice decision.

## Program001 — Foundation

Initial vertical slice:

1. English onboarding
2. State check-in
3. State → practice selection
4. Structured 5-minute practice protocol
5. Session execution
6. Before/after feedback
7. Session history

## Architecture principles

- Individual-first commercial launch; incorporation only after real subscription/revenue validation.
- US-first, English-first, with EU readiness designed but not allowed to block MVP.
- Wellness/mindfulness positioning; no medical diagnosis or treatment claims.
- Flutter client target for iOS and Android.
- FastAPI + PostgreSQL backend sized for the existing OCI A1 2 OCPU / 12 GB / 200 GB environment.
- OCI is the control/data plane, not a large-model GPU inference host.
- Provider-neutral AI and TTS adapters.
- Canonical practice knowledge and protocol selection remain deterministic/source-grounded; generative AI personalizes presentation only.
- HealthKit/Health Connect/camera/biometric inference are deferred until after V1 store release.
- Privacy, deletion, export, AI safety, store declarations and subscription entitlement are architecture concerns from day one.

## Programs

- Program001: Platform Foundation
- Program002: Practice Intelligence
- Program003: Individual-first Commercialization & Store Compliance
- Program004: Core Adaptive Meditation Experience
- Program005: Personalization
- Program006: Commerce
- Program007: Apple/Google Store Release
- Program008: Optional Health Integrations

## Repository

```text
api/          generated OpenAPI contract
apps/mobile/  Flutter client
backend/      FastAPI modular monolith, PostgreSQL, Alembic
compliance/   machine-readable data and permission inventories
docs/         program contract and SDD, plus implementation status
infra/        OCI-sized Docker Compose stack and Caddy config
knowledge/    versioned practice and protocol knowledge (v1 frozen, v2 current)
```

## Running the vertical slice

```bash
# backend
cd backend && python3.12 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://adaptive:adaptive@localhost:5432/adaptive"
./.venv/bin/alembic upgrade head && ./.venv/bin/uvicorn app.main:app --reload

# client
cd apps/mobile && flutter pub get
flutter run --dart-define=API_BASE_URL=http://localhost:8000

# whole stack on the OCI host
cd infra && cp .env.example .env && $EDITOR .env && docker compose up -d
```

No AI or TTS credential is required. Without one the deterministic engine is the
only recommendation path, which is the intended V1 behaviour.

## Status

**Program001 — closed.** The vertical slice runs end to end: check-in, state
vector, deterministic recommendation, protocol, session and feedback, through
both the API and the client. Merged to `main`, hosted CI green.
See [docs/PROGRAM001_STATUS.md](docs/PROGRAM001_STATUS.md).

**Program002 — Practice Intelligence & Outcome Evidence, in progress.** Seven
executable practices, scored candidate selection with three independent version
fields, goal-specific outcome evidence over raw before/after values,
backend-persistent guest history with real deletion and export, deterministic
experiment assignment, and an offline rule-set comparator over the full
1,317,690-state space. Nothing learns autonomously and no model selects a
practice: evidence informs an offline comparison, a human approves a versioned
rule set, and the production path stays deterministic.
See [docs/SDD_PROGRAM002.md](docs/SDD_PROGRAM002.md) and
[docs/PROGRAM002_STATUS.md](docs/PROGRAM002_STATUS.md).
