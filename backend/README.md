# Backend

Program001 target: Python 3.12+, FastAPI, Pydantic and PostgreSQL.

The first implementation must expose the OpenAPI vertical slice in `api/openapi.v1.yaml` and keep deterministic practice selection in a domain module independent of any LLM provider.

Planned module boundary:

```text
backend/app/
  main.py
  api/
  domain/
    state/
    practice/
    recommendation/
    session/
  ai/
    providers/
    safety/
  persistence/
```

Large local language models are explicitly out of scope for the OCI A1 production host.
