# Program001 — implementation status

## Disposition

**PROGRAM001_REMOTE_CLOSED**

Authoritative gate: hosted GitHub Actions, all four jobs green.

| Field | Value |
|-------|-------|
| Verified SHA | `c9b90f544b66c1b9ff3ecb97d8a424e0b027d2a4` |
| Workflow run | [34594030538](https://github.com/Thomas94054801/adaptive-meditation/actions/runs/34594030538) |
| Backend (lint, types, tests) | success |
| Backend image (linux/arm64) | success |
| Flutter (analyze, tests) | success |
| No committed credential | success |
| Prior green run | [34593831590](https://github.com/Thomas94054801/adaptive-meditation/actions/runs/34593831590) at `66ee4ca6`, all four jobs success |

The commit that records this disposition is documentation-only and changes no
executable source; the SHA named above is the one the hosted run measured.

Verified on 2026-09-11 against branch `program001/foundation`.

Every result below was produced by running the stated command. Nothing is marked
PASS on inspection alone.

## Definition of Done (SDD section 19)

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Backend starts locally | PASS | `uvicorn app.main:app` serves; the same image starts in Docker and answers `/healthz` |
| 2 | `/healthz` returns 200 | PASS | 200 with `{"status":"ok","practices_loaded":6,"protocols_loaded":6,"ai_provider_configured":false}`, with no database attached and no AI key |
| 3 | Deterministic engine passes all required tests | PASS | SDD 15.1 cases 1–10 in `backend/tests/test_recommendation_engine.py`, plus invariants over 119,790 states (corrected: this figure was first reported as 7,260, which was an arithmetic error, not a different measurement) |
| 4 | Knowledge/protocol cross-validation passes | PASS | `backend/tests/test_knowledge_validation.py`, 15 tests, each mutating a copy of the real knowledge files |
| 5 | check-in → recommendation → session → feedback through API tests | PASS | `backend/tests/test_api.py`, including the full slice for all six goals |
| 6 | PostgreSQL migration exists | PASS | `backend/migrations/versions/0001_initial_program001_schema.py`; applied and downgraded against PostgreSQL 16.15 |
| 7 | Docker image builds for the backend | PASS | `docker build -f backend/Dockerfile .` → `linux/arm64`, 72.9 MB |
| 8 | Flutter project analyzes successfully | PASS | `flutter analyze` → no issues, Flutter 3.47.3 / Dart 3.13.3 |
| 9 | No prohibited V1 mobile permission introduced | PASS | `INTERNET` only; `apps/mobile/test/permissions_manifest_test.dart` checks both manifests against `compliance/permissions.v1.yaml` |
| 10 | CI workflow exists | PASS | `.github/workflows/ci.yml`, four jobs, all green on hosted run 34594030538 |
| 11 | No secret committed | PASS | The CI scanner run over 156 tracked files reports clean; `.env` shapes and key material are ignored |
| 12 | Documentation synchronized with implementation | PASS | This file, the three READMEs, and a generated `api/openapi.v1.yaml` that CI fails on if stale |

Overall: **PASS** — every Definition-of-Done item is satisfied and the hosted CI gate is green.

## Verification commands and results

Backend, from `backend/`:

| Command | Result |
|---------|--------|
| `ruff check .` | All checks passed |
| `ruff format --check .` | 48 files already formatted |
| `mypy` | Success: no issues found in 34 source files |
| `TEST_DATABASE_URL=postgresql+psycopg://…/adaptive_test pytest` | 164 passed |
| `pytest` (SQLite fallback) | 163 passed, 1 skipped (a PostgreSQL-only JSONB assertion) |
| `python scripts/export_openapi.py --check` | matches the implementation |
| `alembic upgrade head` / `alembic downgrade base` | applied and reversed on PostgreSQL 16.15 |
| live `uvicorn` run against PostgreSQL: check-in → recommendation → session → start → feedback over HTTP | session row reads `completed`, `body_awareness_v1`, `user_id` null |

Client, from `apps/mobile/`:

| Command | Result |
|---------|--------|
| `flutter analyze` | No issues found |
| `flutter test` | 41 passed |

Image, from the repository root:

| Command | Result |
|---------|--------|
| `docker build -f backend/Dockerfile -t adaptive-meditation-api:program001 .` | succeeded, `arm64/linux`, 72.9 MB |
| container `/healthz` with no database and no AI key | 200 |
| container `/v1/recommendations` with no database and no AI key | 200, `body_awareness` |
| `docker exec … id` | `uid=999(app)` — non-root |
| `docker stats` | 147.5 MiB against the 768 MB ceiling |
| `docker compose config` (from `infra/`) | resolves; limits 768 MiB api, 1536 MiB db, 128 MiB proxy - 2.4 GiB of the host's 12 GB |

## Performance measurements

**MEASUREMENT ENVIRONMENT: Apple Silicon (arm64) macOS workstation, Python 3.12.14.**
**NOT AN OCI A1 MEASUREMENT.** No number in this section was taken on the
production host. OCI Ampere A1 cores are slower than this workstation's, so
expect a constant-factor increase on the target; these figures establish the
order of magnitude, not the production latency.

SDD section 16 asks for deterministic recommendation p95 comfortably below
100 ms excluding network latency.

| Path | p50 | p95 | p99 | max | n |
|------|-----|-----|-----|-----|---|
| `engine.recommend` (pure domain) | 0.0063 ms | 0.0068 ms | 0.0074 ms | 0.5546 ms | 20,000 |
| recommend + render full session plan | 0.0362 ms | 0.0430 ms | — | 0.1313 ms | 10,000 |
| `POST /v1/recommendations` (in-process, no network) | 0.939 ms | 1.126 ms | 1.345 ms | 15.517 ms | 3,000 |

Cycled over 360 distinct valid check-ins. The pure domain p95 is roughly four
orders of magnitude inside the budget; the HTTP path, which adds request
validation, routing and serialization, is about 90x inside it.

## Resource measurements

**MEASUREMENT ENVIRONMENT: Colima VM on the same Apple Silicon workstation.**
**ACTUAL OCI DEPLOYMENT: NOT YET MEASURED.**

| Quantity | Value |
|----------|-------|
| Docker container RSS observed under Colima | 147.5 MiB |
| Configured container ceiling | 768 MiB |
| Compose total configured ceiling | 2.4 GiB of the host's 12 GiB |
| Image size / architecture | 72.9 MB, `linux/arm64` |
| Container user | uid 999 (non-root) |
| Measured on an OCI Ampere A1 host | NOT YET MEASURED |

The container RSS above is a single-container observation under a local VM, not
a load test and not the production host. Treat it as evidence that the design
fits the budget with large headroom, not as a production capacity figure.

## The required verification case

`goal=overthinking, mental_activity=9, stress=8` returns, through the domain
engine, the HTTP API and the container:

```json
{
  "practice_id": "body_awareness",
  "duration_minutes": 10,
  "guidance_density": 0.7,
  "reason_codes": ["goal_overthinking", "high_mental_activity", "high_stress"],
  "recommendation_version": "1"
}
```

## Known gaps

1. **`kindness` is declared but unreachable.** It has a validated executable
   protocol, and no V1 rule selects it. This is the SDD's rule set, not a defect;
   `test_reachable_practice_set_is_exactly_as_documented` pins the reachable set
   so the gap cannot be forgotten. Program002 is where it earns a rule.
2. **`energy` is collected and unused.** No V1 rule reads it, and a test asserts
   that the outcome is invariant to it, so the field is honest about being
   future input rather than silently ignored.
3. **Session history is in-memory only.** It holds the current run of the app,
   is capped at 50 entries, and the screen says so rather than implying
   durability that does not exist.
4. **No accounts, so no deletion endpoint.** `/delete-account` explains what
   guest data is instead of claiming a capability the service does not have.
5. **No OCI deployment has been performed.** The stack is sized and buildable
   for the target, but nothing has been deployed and no OCI credential is
   configured in this repository.
