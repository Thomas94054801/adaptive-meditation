# Backend

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 and PostgreSQL 16. A modular
monolith: one process, one deployable, boundaries enforced by imports.

## Layout

```text
backend/app/
  main.py                  application factory, error envelope
  settings.py              environment-driven config, all with working defaults
  api/
    deps.py                request-scoped dependencies
    system.py              /healthz and the public policy pages
    v1/routes.py           check-in, recommendation, session, start, feedback
    v1/schemas.py          wire models
  domain/                  pure logic: no HTTP, no database, no provider
    state/models.py        CheckIn and the normalized StateVector
    practice/catalog.py    knowledge loader and cross-validator
    practice/language.py   non-clinical, non-sectarian wording guard
    recommendation/rules.py    priority-ordered rules, duration and density policy
    recommendation/engine.py   the deterministic engine
    session/planner.py     exact stage-timeline rendering
    session/service.py     engine plus renderer
  persistence/             SQLAlchemy models, engine, repositories
  ai/                      provider and safety boundaries, envelope guard
```

## The deterministic core

`RecommendationEngine` is pure. For one rules version and one knowledge catalog,
equal normalized input produces an equal recommendation, field for field,
including reason-code order. It opens no socket and reads no database - there is
a test that fails if it tries.

Large local language models are out of scope for the OCI A1 host, and no
external model is involved in selecting a practice. `AI_API_KEY` is optional;
without it the null provider is used and nothing degrades.

## Running it

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

export DATABASE_URL="postgresql+psycopg://adaptive:adaptive@localhost:5432/adaptive"
./.venv/bin/alembic upgrade head
./.venv/bin/uvicorn app.main:app --reload
```

`/healthz` and `/v1/recommendations` answer even with the database down.

## Tests

```bash
./.venv/bin/pytest                                    # SQLite fallback
TEST_DATABASE_URL="postgresql+psycopg://user@localhost:5432/adaptive_test" \
  ./.venv/bin/pytest                                  # production dialect
```

The suite builds its schema by running the real Alembic migration, so a model
that drifts from the migration fails the tests rather than the deployment.

## Contract

`api/openapi.v1.yaml` is generated from this implementation:

```bash
./.venv/bin/python scripts/export_openapi.py          # regenerate
./.venv/bin/python scripts/export_openapi.py --check  # fail if stale
```
