# Software Design Document (SDD)

## Project
Adaptive Meditation — Program002 — Practice Intelligence & Outcome Evidence

## Document status
This document is the implementation contract for Program002. It is committed
before any Program002 implementation commit, and no implementation commit may
widen the scope defined here.

Program001's contract is `SDD_PROGRAM001.md`; its verified result is
`PROGRAM001_STATUS.md`. Program002 builds on that foundation and does not
re-open it.

---

## 1. Core principle

Program002 closes one loop:

```text
outcome evidence  →  offline comparison  →  versioned rule approval
```

It explicitly does **not**:

- perform autonomous learning of any kind;
- use an LLM to select a practice;
- let user feedback modify production rules, directly or indirectly.

Feedback becomes *evidence*. Evidence feeds an *offline* comparator. A human
reads the comparator output and approves a new *versioned* rule set. The
production path stays deterministic and inspectable at every step.

A rule set that changed itself in response to outcomes would make every earlier
recommendation unreproducible and every stored `recommendation_version`
meaningless. That is the failure this design exists to prevent.

---

## 2. Scope

### 2.1 StateVector V2 — `energy` becomes meaningful

`energy` is collected today and read by no rule. Program001 pinned it and proved
the outcome invariant to it, which made the gap honest but did not close it.

Program002 must take option **A**: `energy` influences at least one verifiable
recommendation rule. Option B (removal) is permitted only if A is shown to
produce no defensible rule, and requires removing the field from the check-in,
the schema, the client and the OpenAPI contract in the same slice.

The chosen rule is the focus/energy interaction specified in section 2.4.

### 2.2 Practice Catalog V2 — seven executable practices

```text
breath_awareness
body_awareness
feeling_tone
thought_observation
kindness
open_awareness
mindful_walking        (new in Program002)
```

Each practice entry gains:

```yaml
id:
public_name:
intent:
suitable_for:
contraindications:        # new: states in which the practice is not offered
minimum_experience:       # new: beginner | intermediate | experienced
duration_range:           # new: [min_minutes, max_minutes]
guidance_density_range:   # new at the practice level
source_basis:             # internal only, unchanged
stages:                   # via the protocol file
outcomes:                 # new: which outcome measures this practice targets
```

`source_basis` remains internal. The public-language guard
(`app/domain/practice/language.py`) continues to apply to every user-facing
field, and `contraindications` and `outcomes` must not introduce clinical
vocabulary — an `outcomes` entry names a self-reported check-in dimension, never
a condition.

### 2.3 `kindness` must be reachable

Golden case B:

```text
goal=emotional_reset, stress=7, mental_activity=4  →  kindness
```

Program001's emotional-reset rule routes beginners to `body_awareness` and
everyone else to `feeling_tone`, so `kindness` is unreachable. Program002 adds a
deterministic rule reaching it. Any alternative mapping must be argued in this
document and covered by a test before it is implemented.

### 2.4 `mindful_walking` and the energy rule

A complete executable protocol is added for `mindful_walking`.

Golden case C:

```text
goal=focus, energy=9, stress=4, available_minutes=10  →  mindful_walking
```

The rule: when the goal is focus and energy is high, seated attention training
fights the body's state instead of using it. High energy with low-to-moderate
stress selects movement-based attention. This is the rule that makes `energy`
meaningful, and it is falsifiable: lowering `energy` alone must change the
outcome, which is Golden case C's test.

Public naming — one of `Mindful Walk`, `Walking Reset`, `Movement Awareness`.
This document selects **`Mindful Walk`**. No Buddhist terminology in any
default-visible string.

`mindful_walking` carries a contraindication for high sleepiness and is not
offered for `goal=sleep`.

### 2.5 Recommendation versioning V2

`recommendation_version = "1"` becomes three independent fields:

```text
engine_version        the scoring/selection machinery
rule_set_version      the rule tables
protocol_version      the knowledge protocol revision
```

Every persisted recommendation stores:

```text
state_fingerprint
engine_version
rule_set_version
protocol_version
practice_id
duration_minutes
guidance_density
reason_codes
created_at
```

**V1 records must remain readable.** A stored recommendation carrying only
`recommendation_version: "1"` must load, replay and compare without error. The
V1 replay test is a permanent fixture, not a migration-time check.

### 2.6 Deterministic candidate scoring

Selection stops being "first rule that matches". The engine builds a candidate
list, scores it, and takes the winner:

```json
{
  "candidates": [
    {"practice_id": "body_awareness", "score": 82,
     "reason_codes": ["high_stress", "high_mental_activity"]}
  ]
}
```

Requirements:

- `score` is a **bounded integer**, 0..100.
- Scoring is deterministic: same state, same version, same scores, same order.
- The score is **not a probability** and must not be presented or documented as
  one. No normalization to 1.0, no percentage sign in any user-facing string.
- Ties are broken by a fixed, documented order so the winner never depends on
  dict or set iteration order.
- The normal API returns the winning practice only. Candidates are available to
  the offline evaluator and to a debug path, never in the default response.

### 2.7 Outcome evidence

Before (from the check-in): `stress`, `energy`, `mental_activity`, `sleepiness`.

After (from feedback): `stress`, `energy`, `mental_activity`, `sleepiness`,
`helpfulness`, `completion_ratio`.

Raw before and after values are persisted permanently and are never overwritten
by a derived value.

An internal `session_outcome_score` may be computed. Wherever it appears — code,
schema comment, document, API field description — it is labelled:

> product optimization metric only

It is **not** a clinical score, a medical score, or a diagnostic score, and no
user-facing surface displays it.

### 2.8 Goal-specific outcome measures

| Goal | Primary measure | Secondary |
|------|-----------------|-----------|
| `stress` | `stress_before - stress_after` | — |
| `overthinking` | `mental_activity_before - mental_activity_after` | — |
| `sleep` | `sleepiness_after - sleepiness_before` | — |
| `focus` | `energy_after - energy_before` | `mental_activity_before - mental_activity_after` |
| `emotional_reset` | `stress_before - stress_after` | — |
| `general` | `helpfulness` | — |

Positive is always "moved in the intended direction". Raw before/after values
are retained regardless of which measure applies.

### 2.9 Guest persistent history

Program001's client history is memory-only. Program002 moves it to the backend.

```text
guest_id = UUIDv4, generated on the client, stored in SecureStorageProvider
```

Prohibited as an identifier source: hardware fingerprint, IMEI, advertising ID,
IDFA/IDFV, MAC address, any device-derived value. No email and no account is
required or requested.

`GET /v1/sessions/history` returns that guest's sessions, paginated.

### 2.10 Guest data deletion

Server-side guest data creates a deletion obligation.

```text
DELETE /v1/me/data
```

Deletes, for that `guest_id`: check-ins, recommendations, sessions, feedback and
experiment assignments. Deletion is by database cascade, verified by a test that
counts rows in every table before and after.

The client offers **"Delete my meditation data"**. No dark pattern: no
pre-checked retention box, no burying the action, no confirm copy that argues
against the user's choice. One clear confirmation step, and it says what will be
deleted.

`/delete-account` stops describing a capability that does not exist and starts
describing one that does.

### 2.11 Data export

```text
GET /v1/me/export
```

JSON, containing at minimum that guest's check-ins, recommendations, sessions
and feedback.

### 2.12 Experiment framework

Deterministic assignment only:

```text
variant = f(hash(guest_id + experiment_id))
```

Never random per request: the same guest and experiment must yield the same
variant on every call, on every process, forever.

Persisted: `experiment_id`, `variant`, `assignment_key`, `assigned_at`.

An experiment may vary presentation and ranking weights. It may **not** cross a
safety invariant: it cannot bypass a contraindication, exceed a duration
envelope, breach a guidance-density range, or introduce a practice below its
`minimum_experience`.

### 2.13 Offline rule-set comparator

```bash
python scripts/compare_rulesets.py --baseline v1 --candidate v2
```

Output must include:

- total states compared;
- changed recommendations (count);
- changed percentage;
- practice distribution, baseline vs candidate;
- duration distribution;
- guidance-density distribution;
- reason-code changes;
- unreachable practices under each rule set.

No network access. No external LLM. It runs from the knowledge files and the
rule tables alone.

### 2.14 Exhaustive state-space test

Program001 tested 7,260 states with `energy` pinned. Once `energy` enters a
rule, that number is no longer a full state space and must not be quoted as one.

`energy = 0..10` enters the enumeration. The new cardinality is:

```text
6 goals x 11 stress x 11 energy x 11 mental_activity x 11 sleepiness
  x 5 durations x 3 experience levels  =  79,860 states
```

The suite reports the cardinality it actually enumerated.

Invariants asserted over the full space:

1. the selected practice exists in the catalog;
2. reason codes stay inside the goal's declared vocabulary;
3. duration is supported by the selected protocol;
4. guidance density is inside the protocol's range;
5. same input and same versions produce identical output;
6. every intended practice is reachable;
7. no contraindication is violated;
8. no practice is offered below its `minimum_experience`;
9. V1 replay is stable.

### 2.15 Experience-level intelligence

`experience_level` must affect both guidance density and ranking:

- **beginner** — higher guidance density; advanced practices rank lower;
- **experienced** — `open_awareness` ranks higher; lower guidance density.

An experienced user must still be able to receive a basic practice: experience
adjusts ranking, it does not remove eligibility. A test asserts that
`breath_awareness` and `body_awareness` remain reachable for experienced users.

### 2.16 Session plan adaptation

The protocol family is fixed by the recommendation. Stage *weights* may adapt
deterministically to the state:

- high stress → grounding stage longer;
- high mental activity → body-observation stage longer;
- experienced → silence longer.

Hard invariant, unchanged from Program001:

```text
sum(stage_seconds) == duration_minutes * 60
```

exactly, for every reachable state, and every stage stays within its declared
`min_seconds`/`max_seconds`.

### 2.17 Store boundary

Program002 adds no permission. Still prohibited: camera, microphone, location,
HealthKit, Health Connect, Garmin, biometric emotion inference, voice cloning.
`compliance/permissions.v1.yaml` remains the declaration and the manifest test
remains the enforcement.

### 2.18 AI boundary

Unchanged:

```text
state → deterministic recommendation → deterministic protocol
      → optional AI wording → envelope validation
```

AI may not alter `practice_id`, safety class, duration envelope or
guidance-density range. Program002 requires no paid AI API, and the system must
start and recommend with no credential present.

### 2.19 Infrastructure boundary

OCI A1 Flex, 2 OCPU, 12 GB RAM, 200 GB storage. No Kubernetes, Kafka,
Elasticsearch, Redis, Celery cluster, large local LLM or GPU requirement may be
introduced without measured evidence that the workload demands it.

### 2.20 PostgreSQL migration

New or altered:

- `guest_profiles`
- recommendation version fields (`engine_version`, `rule_set_version`,
  `protocol_version`, `state_fingerprint`)
- `recommendation_candidates`
- enhanced feedback/outcome columns
- `experiment_assignments`

Every migration is verified by running, against PostgreSQL 16:

```bash
alembic upgrade head
alembic downgrade <previous>
alembic upgrade head
```

### 2.21 Performance targets

| Path | Target |
|------|--------|
| domain recommendation | p95 < 20 ms |
| recommendation API | p95 < 150 ms |
| history API | p95 < 300 ms |

Every measurement records its environment. An Apple Silicon workstation figure
is never reported as an OCI figure, and the two are never averaged or conflated.

---

## 2.22 Scoring model

Selection is a scored ranking over eligible candidates, not a first-match cascade.

**Eligibility (hard filters, applied before scoring).** A practice is removed
from the candidate list, not scored low, when:

- a `contraindications` entry matches the state;
- `experience_level` is below the practice's `minimum_experience`;
- the catalog has no executable protocol for it.

Removal is recorded so the offline evaluator can see why a practice was absent.

**Base affinity.** Each goal declares a base score per practice, 0..100.

**Modifiers.** A modifier is a `(condition, practice, delta, reason_code)` tuple.
A condition may read any StateVector field, including the goal. Every modifier
that fires contributes its reason code, so the explanation is generated from the
same data that produced the score rather than written separately.

**Clamping and tie-breaking.** The final score is clamped to 0..100. Ordering is
`(-score, declaration_index)`, where `declaration_index` is the practice's fixed
position in the `PracticeId` enum. No ordering ever depends on dict, set or hash
iteration order.

**The score is not a probability.** It is an ordinal ranking aid with no
calibration and no frequency interpretation. It must never be normalised to 1.0,
rendered with a percentage sign, or described as a confidence or likelihood.

## 2.23 Declared behaviour changes from rule set v1

These changes are intentional and outside the golden cases. They are listed in
advance so a comparator diff can be checked against an expectation rather than
accepted because it appeared.

Measured over the full 1,317,690-state space, rule set v1 and rule set v2 on
knowledge v2 differ in **136,125 states (10.33%)**, in exactly four transitions:

| Transition | States | Cause |
|------------|-------:|-------|
| `breath_awareness` → `mindful_walking` | 50,820 | The energy rule (2.4): focus with high energy uses movement |
| `feeling_tone` → `kindness` | 42,350 | The kindness window (2.3) |
| `breath_awareness` → `body_awareness` | 21,780 | Stress in 5..7 with a racing mind grounds rather than anchoring on the breath |
| `body_awareness` → `kindness` | 21,175 | The kindness window (2.3), for beginners |

Any transition not in this table is a defect until it is either fixed or added
here with a reason. Two were found and fixed this way rather than accepted:

- unscoped sleepiness and energy modifiers pushed `body_awareness` to 76% of all
  states and the diff to 44%. Modifiers are now scoped by goal, because
  sleepiness is an obstacle when the user wants focus and the point of the
  session when they want sleep;
- at equal weight, `sleepy_body` tied with `low_energy_breath` and the tie-break
  handed sleepy focus sessions to the breath. Sleepiness is the stronger signal
  for that goal, so it must not tie.

Reason codes are also preserved where the practice is unchanged. Golden case A
returns `body_awareness` with `["goal_overthinking", "high_mental_activity",
"high_stress"]` under both rule sets - identical practice, duration, density and
codes. Three explanation-only modifiers (zero delta, one reason code) keep the
v1 wording for sleep, focus and emotional-reset recommendations that v2 still
makes.

Practice reachability, measured over the same space:

| Rule set | Unreachable practices |
|----------|-----------------------|
| v1 | `kindness`, `mindful_walking` |
| v2 | none |

## 3. Golden cases

### A — V1 behaviour preserved

```text
goal=overthinking, mental_activity=9, stress=8  →  body_awareness
```

If Program002 changes this, it requires a version bump, an explicit comparator
line showing the change, and a stated reason in this document. Silent change is
prohibited.

### B — kindness reachable

```text
goal=emotional_reset, stress=7, mental_activity=4  →  kindness
```

### C — energy is load-bearing

```text
goal=focus, energy=9, stress=4, available_minutes=10  →  mindful_walking
```

Lowering `energy` alone must change the result, proving the field is read.

### D — open_awareness eligible

```text
goal=general, experience_level=experienced, stress=2, mental_activity=3
  →  open_awareness eligible
```

---

## 4. Required verification

Backend:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

Client:

```bash
flutter analyze
flutter test
```

Migration, against PostgreSQL 16:

```bash
alembic upgrade head && alembic downgrade <previous> && alembic upgrade head
```

Contract:

```bash
python scripts/export_openapi.py --check
```

Image and stack:

```bash
docker build -f backend/Dockerfile .
docker compose config
```

Additional required tests:

- exhaustive full state-space test (with `energy` enumerated);
- deterministic replay;
- V1 backward replay;
- `kindness` reachability;
- `mindful_walking` reachability;
- `energy` sensitivity;
- guest history persistence;
- delete cascade;
- export completeness;
- deterministic experiment assignment;
- rule comparator golden output.

Prohibited in pursuit of a green build: deleting a test, adding an
unjustified skip, weakening a type or static check, removing the credential
scan, or reporting a local pass as a hosted pass.

---

## 5. Definition of Done

Program002 is COMPLETE only when every item passes:

- [ ] Program001 remote closed
- [ ] Program001 hosted CI green
- [ ] PR #1 implementation merged
- [ ] Program002 SDD committed before implementation
- [ ] Program002 branch from validated main
- [ ] `energy` meaningful or removed
- [ ] `kindness` reachable
- [ ] `mindful_walking` executable
- [ ] all intended practices reachable
- [ ] v2 recommendation versioning
- [ ] deterministic candidate scoring
- [ ] raw before/after persisted
- [ ] outcome evidence computed
- [ ] guest history backend persistent
- [ ] guest delete works
- [ ] guest export works
- [ ] deterministic experiment assignment
- [ ] rule-set comparator works
- [ ] exhaustive state space passes
- [ ] V1 replay preserved
- [ ] PostgreSQL migration upgrade/downgrade passes
- [ ] Flutter history migrated to backend
- [ ] no new sensitive permissions
- [ ] no external AI dependency
- [ ] ARM64 Docker build passes
- [ ] resource budget acceptable
- [ ] hosted CI green

A partial implementation is reported as PARTIAL, never as COMPLETE.

---

## 6. Product invariants carried forward

1. wellness, not medical diagnosis or treatment;
2. source-grounded internally, non-sectarian in user-facing language;
3. deterministic core, independent of any external AI;
4. guest-first usability;
5. OCI A1 resource discipline;
6. store-sensitive capabilities deferred or isolated;
7. individual-first commercialization with future company migration;
8. no false test or deployment claims.
