# Program002 — implementation status

Practice Intelligence & Outcome Evidence. Contract: `SDD_PROGRAM002.md`.

## Disposition

**PROGRAM002_IMPLEMENTED_CI_GREEN** — not closed. Closure requires the PR to be
merged to `main`, which is an operator decision, not an agent one.

| Field | Value |
|-------|-------|
| Branch | `program002/practice-intelligence` |
| Pull request | [#2](https://github.com/Thomas94054801/adaptive-meditation/pull/2) |
| Verified SHA | `6601fdf5c0a3ef252c21ff08a99ccd4185f6c574` |
| Workflow run | [34612905298](https://github.com/Thomas94054801/adaptive-meditation/actions/runs/34612905298) |
| Backend (lint, types, tests) | success |
| Backend image (linux/arm64) | success |
| Flutter (analyze, tests) | success |
| No committed credential | success |

Every result below was produced by running the stated command. Nothing is marked
PASS on inspection alone, and no local result is reported as a hosted or OCI
result.

## Definition of Done

| Item | Result | Evidence |
|------|--------|----------|
| Program001 remote closed | PASS | `PROGRAM001_STATUS.md`, run 34594243634 green at `7bdbb24` |
| Program001 hosted CI green | PASS | Four jobs green on hosted GitHub Actions |
| PR #1 implementation merged | PASS | Merged 2026-09-11, merge commit `a08c03a8` |
| Program002 SDD committed before implementation | PASS | `6fd010e` precedes every implementation commit |
| Program002 branch from validated main | PASS | Branched from `a08c03a8` after the merge |
| `energy` meaningful or removed | PASS | Focus + high energy selects `mindful_walking`; lowering energy alone changes the result |
| `kindness` reachable | PASS | Golden B; reachable in the full-space enumeration |
| `mindful_walking` executable | PASS | `mindful_walking_v2`, five stages, renders 3–20 minutes |
| All intended practices reachable | PASS | Comparator reports no unreachable practice under v2 |
| v2 recommendation versioning | PASS | `engine_version` / `rule_set_version` / `protocol_version` + `state_fingerprint` |
| Deterministic candidate scoring | PASS | Bounded 0..100 integers, fixed tie-break, ordering asserted |
| Raw before/after persisted | PASS | Four after-scales stored; derived fields never overwrite them |
| Outcome evidence computed | PASS | Goal-specific measures, verified per goal |
| Guest history backend persistent | PASS | `GET /v1/sessions/history`, keyset pagination |
| Guest delete works | PASS | Cascade verified by per-table row counts scoped to one guest |
| Guest export works | PASS | Five categories returned and asserted |
| Deterministic experiment assignment | PASS | sha256 bucketing, hardcoded expectation |
| Rule-set comparator works | PASS | `scripts/compare_rulesets.py`, full 1,317,690-state run |
| Exhaustive state space passes | PASS | 1,317,690 states, eight invariants in one pass |
| V1 replay preserved | PASS | `tests/test_v1_replay.py`, frozen Program001 matrix |
| PostgreSQL migration upgrade/downgrade passes | PASS | `upgrade → downgrade 0001 → upgrade` on PostgreSQL 16.15, no pending diff |
| Flutter history migrated to backend | PASS | `HistoryScreen` reads the API; no in-memory claim remains |
| No new sensitive permissions | PASS | `INTERNET` only; manifest test asserts against the declaration |
| No external AI dependency | PASS | Null provider; container serves with no key |
| ARM64 Docker build passes | PASS | See the image section below |
| Resource budget acceptable | PASS | See the resource section below |
| Hosted CI green | PASS | Run 34612905298, all four jobs, at `6601fdf` |

## Verification commands and results

Backend, from `backend/`:

| Command | Result |
|---------|--------|
| `ruff check .` | All checks passed |
| `ruff format --check .` | all files already formatted |
| `mypy` | Success: no issues found in 43 source files |
| `pytest` (PostgreSQL 16.15) | 233 passed |
| `alembic upgrade head` / `downgrade 0001` / `upgrade head` | applied and reversed |
| `python scripts/export_openapi.py --check` | matches the implementation |
| `python scripts/compare_rulesets.py --baseline v1 --candidate v2` | 1,317,690 states compared |

Client, from `apps/mobile/`:

| Command | Result |
|---------|--------|
| `flutter analyze` | No issues found |
| `flutter test` | 52 passed |

## Rule set v1 vs v2

Measured over the full state space, both rule sets against knowledge v2:

| Quantity | Value |
|----------|-------|
| States compared | 1,317,690 |
| Changed recommendations | 136,125 |
| Changed percentage | 10.33% |
| Duration distribution | unchanged |
| Unreachable under v1 | `kindness`, `mindful_walking` |
| Unreachable under v2 | none |

Exactly four transitions, all declared in SDD section 2.23:

| Transition | States |
|------------|-------:|
| `breath_awareness` → `mindful_walking` | 50,820 |
| `feeling_tone` → `kindness` | 42,350 |
| `breath_awareness` → `body_awareness` | 21,780 |
| `body_awareness` → `kindness` | 21,175 |

The comparator rejected two earlier versions of the rule set before this one:
unscoped modifiers had pushed `body_awareness` to 76% of all states, and a
scoring tie handed sleepy focus sessions to the breath. Both are recorded in
SDD section 2.23.

## State space

| Program | Enumeration | Cardinality |
|---------|-------------|------------:|
| Program001 | energy pinned | 119,790 |
| Program002 | energy enumerated 0..10 | 1,317,690 |

Program001's own report gave 7,260. That was an arithmetic slip in the
write-up, not a smaller test; `PROGRAM001_STATUS.md` carries the correction. A
test now pins the cardinality so the documented number cannot drift from the
enumerated one.

## Practice reachability

All seven practices are reachable under rule set v2: `breath_awareness`,
`body_awareness`, `feeling_tone`, `thought_observation`, `kindness`,
`open_awareness`, `mindful_walking`.

`open_awareness` is never offered below `intermediate`, and `mindful_walking`
is never offered for sleep or to a sleepy user. Both are asserted over the
sampled space, and an experienced user can still receive a basic practice.

## Performance measurements

**MEASUREMENT ENVIRONMENT: Apple Silicon (arm64) macOS workstation, Python
3.12.14, PostgreSQL 16.15 running locally.**
**NOT AN OCI A1 MEASUREMENT.** No figure here was taken on the production host.

| Path | p50 | p95 | p99 | Target | Result |
|------|-----|-----|-----|--------|--------|
| domain recommendation | 0.028 ms | 0.030 ms | 0.033 ms | p95 < 20 ms | PASS |
| recommendation API | 0.956 ms | 1.070 ms | 1.343 ms | p95 < 150 ms | PASS |
| history API (60 sessions) | 6.988 ms | 7.446 ms | 8.495 ms | p95 < 300 ms | PASS |
| export API (60 sessions) | 14.119 ms | 14.992 ms | 30.229 ms | — | — |

n = 20,000 / 3,000 / 600 / 200.

## Known gaps

1. **No OCI deployment.** Nothing has been deployed and no OCI credential is
   configured in this repository. Every resource and latency figure above is
   from this workstation.
2. **The experiment framework has one experiment and no consumer.** Assignment
   is deterministic, persisted and tested, but no rule or screen reads a
   variant yet. It is infrastructure ahead of its first use, recorded here so
   it does not become invisible unreachable capability.
3. **`outcome_score` has no consumer either.** It is computed and stored; no
   promotion or demotion depends on it, and nothing displays it.
4. **Guest storage is not encrypted at rest.** App-private preferences, not the
   keychain. Appropriate for an opaque non-credential identifier, recorded as
   `encrypted_at_rest: false` in the compliance manifest.
5. **Session plan adaptation is unmeasured.** Stage weights adapt and the total
   stays exact, but no evidence says the adapted plan produces better outcomes.
6. **The suite is not safe to run twice concurrently against one database.**
   The schema fixture drops and recreates it per session, so two simultaneous
   local runs corrupt each other - observed once as 12 spurious failures, which
   disappeared on a clean single run (234 passed, twice). CI is unaffected: each
   run gets its own PostgreSQL service container. Worth fixing with a per-run
   schema or database name before anyone runs the suite in parallel locally.
