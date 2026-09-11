# Software Design Document (SDD)

## Project
Adaptive Meditation — Program001

## Document purpose
This document is the implementation contract for Claude or another coding agent. The agent is expected to implement, test, and integrate the first executable vertical slice of the product in the existing repository without redesigning the product scope unless a concrete defect requires it.

---

## 1. Product objective

Build a US-first, English-first adaptive meditation product that converts a user's current state into a suitable contemplative practice, generates a structured session, executes the session, and records outcome feedback.

The V1 product positioning is wellness/mindfulness, not medical diagnosis or treatment.

Primary user jobs:

1. Calm stress
2. Quiet overthinking
3. Improve focus
4. Prepare for sleep
5. Emotional reset
6. General meditation practice

The product incorporates source-grounded contemplative methods internally but does not emphasize religious identity in user-facing language.

---

## 2. Existing constraints

### 2.1 Infrastructure

Production target:

- OCI Ampere A1 Flex
- ARM64
- 2 OCPU
- 12 GB RAM
- 200 GB storage

Do not introduce Kubernetes, Kafka, Elasticsearch, service mesh, large local LLM inference, or other infrastructure that materially exceeds this resource envelope.

### 2.2 Client

Target framework: Flutter.

Target stores:

- Apple App Store
- Google Play

V1 excludes:

- HealthKit
- Health Connect
- Garmin
- camera posture analysis
- microphone requirement
- biometric emotion inference
- creator voice cloning

### 2.3 Commercial model

Initial publisher/developer is an individual, not a company.

Architecture must avoid binding the product identity to the individual's legal name so later migration to a company does not require a product rewrite.

### 2.4 AI boundary

AI is presentation intelligence, not doctrine or protocol authority.

The deterministic Practice Engine owns:

- practice family
- suitability
- duration envelope
- guidance density envelope
- safety constraints
- progression rules

A generative model may later personalize wording but must not silently change the selected practice family, safety rules, or protocol envelope.

The first vertical slice MUST operate without any external LLM API key.

---

## 3. Repository target structure

Implement toward the following structure. Existing files should be preserved unless they conflict with this contract.

```text
adaptive-meditation/
├── apps/
│   └── mobile/
│       ├── lib/
│       │   ├── app/
│       │   ├── core/
│       │   ├── features/
│       │   │   ├── check_in/
│       │   │   ├── recommendation/
│       │   │   ├── session/
│       │   │   └── feedback/
│       │   └── platform/
│       └── test/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── domain/
│   │   │   ├── state/
│   │   │   ├── practice/
│   │   │   ├── recommendation/
│   │   │   └── session/
│   │   ├── persistence/
│   │   ├── ai/
│   │   │   ├── providers/
│   │   │   └── safety/
│   │   └── settings.py
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── api/
│   └── openapi.v1.yaml
│
├── knowledge/
│   ├── practices.v1.yaml
│   └── protocols.v1.yaml
│
├── compliance/
│   ├── data-inventory.v1.yaml
│   └── permissions.v1.yaml
│
├── infra/
│   ├── docker-compose.yml
│   └── Caddyfile
│
├── docs/
│   ├── PROGRAM001.md
│   └── SDD_PROGRAM001.md
│
└── .github/
    └── workflows/
        └── ci.yml
```

Do not create placeholder microservices. Keep the backend a modular monolith.

---

## 4. Core domain model

### 4.1 CheckIn

```text
CheckIn
- goal
- stress: 0..10
- energy: 0..10
- mental_activity: 0..10
- sleepiness: 0..10
- available_minutes: 3 | 5 | 10 | 15 | 20
- experience_level: beginner | intermediate | experienced
```

Allowed `goal` values:

- stress
- overthinking
- focus
- sleep
- emotional_reset
- general

Validation MUST reject out-of-range or unsupported values with HTTP 422.

### 4.2 Practice

Initial practice IDs:

- breath_awareness
- body_awareness
- feeling_tone
- thought_observation
- kindness
- open_awareness

Public labels are defined in `knowledge/practices.v1.yaml`.

Internal source mappings must remain internal metadata and must not be required in the default user-facing API response.

### 4.3 Recommendation

```text
Recommendation
- practice_id
- duration_minutes
- guidance_density: 0.0..1.0
- reason_codes[]
- recommendation_version
```

Recommendation generation MUST be deterministic for identical normalized inputs and the same rules version.

### 4.4 Session

```text
Session
- id
- check_in
- recommendation
- protocol_version
- started_at
- completed_at
- status
```

Status values:

- created
- started
- completed
- abandoned

### 4.5 Feedback

```text
SessionFeedback
- before_score: 0..10 optional when already derivable from check-in
- after_score: 0..10
- helpfulness: 1..5
- completed: bool
- notes: optional text, max 1000 chars
```

The MVP does not infer clinical meaning from these values.

---

## 5. Deterministic State → Practice Engine

Implement as pure domain logic with no database dependency and no external service calls.

The implementation must be easy to unit test.

### 5.1 Initial rules

Rules are priority-ordered. The engine must emit reason codes to explain why a recommendation was selected.

#### Sleep

If `goal == sleep`:

- if `mental_activity >= 7`: primary `body_awareness`, fallback `breath_awareness`
- otherwise: `body_awareness`
- guidance density for beginners: 0.65
- intermediate: 0.50
- experienced: 0.35

Reason codes may include:

- goal_sleep
- high_mental_activity
- grounding_preferred

#### Overthinking

If `goal == overthinking`:

- if `mental_activity >= 7` and `stress >= 6`: `body_awareness`
- elif `mental_activity >= 7`: `thought_observation`
- else: `breath_awareness`

Reason codes:

- goal_overthinking
- high_mental_activity
- high_stress
- cognitive_observation

#### Stress

If `goal == stress`:

- if `stress >= 8`: `body_awareness`
- elif `stress >= 5`: `breath_awareness`
- else: `open_awareness` for experienced users, otherwise `breath_awareness`

Reason codes:

- goal_stress
- very_high_stress
- moderate_stress
- experienced_open_awareness

#### Focus

If `goal == focus`:

- if `sleepiness >= 7`: `body_awareness`
- otherwise: `breath_awareness`

Reason codes:

- goal_focus
- high_sleepiness
- stabilize_attention

#### Emotional reset

If `goal == emotional_reset`:

- beginner: `body_awareness`
- intermediate: `feeling_tone`
- experienced: `feeling_tone`

Reason codes:

- goal_emotional_reset
- recognize_reactivity

#### General

If `goal == general`:

- beginner: `breath_awareness`
- intermediate: `body_awareness`
- experienced: `open_awareness`

Reason codes:

- goal_general
- experience_progression

### 5.2 Duration policy

`duration_minutes` must not exceed `available_minutes`.

Initial selection:

- available 3 → 3
- available 5 → 5
- available 10 → 10
- available 15 → 10 for beginner, 15 otherwise
- available 20 → 10 for beginner, 15 intermediate, 20 experienced

### 5.3 Guidance density policy

Base density by experience:

- beginner = 0.65
- intermediate = 0.50
- experienced = 0.35

Adjustments:

- high stress (`stress >= 8`): +0.05, capped at 0.75
- sleep goal: no density above 0.65
- open_awareness: -0.10, floor 0.20

Return final normalized value rounded to two decimals.

### 5.4 Safety behavior

The deterministic engine is not a crisis classifier. However the architecture must include a pre-generation `SafetyRouter` interface so a future free-text prompt cannot flow directly into an LLM.

For Program001, implement:

```python
class SafetyRouter(Protocol):
    def classify(self, text: str) -> SafetyDecision: ...
```

and a `NoopSafetyRouter` used by tests/local operation. Do not claim clinical detection capability.

---

## 6. Practice protocol model

Create `knowledge/protocols.v1.yaml` with one executable protocol for each initial practice.

Each protocol must include:

```text
id
version
practice_id
public_title
duration_supported
guidance_density_range
stages[]
```

Each stage:

```text
id
intent
min_seconds
max_seconds
prompt_template
silence_after_seconds
```

Example conceptual structure:

```yaml
id: breath_awareness_v1
version: 1
practice_id: breath_awareness
public_title: Breath Awareness
duration_supported: [3, 5, 10, 15, 20]
guidance_density_range: [0.30, 0.75]
stages:
  - id: arrive
    intent: establish_posture
  - id: contact
    intent: notice_natural_breath
  - id: stabilize
    intent: return_without_force
  - id: close
    intent: transition_out
```

Do not use therapeutic or diagnostic claims in prompt templates.

Do not hard-code religious terminology into the default public title or prompt template.

---

## 7. REST API

The implementation must conform to or update `api/openapi.v1.yaml` consistently.

Required endpoints:

### POST `/v1/check-ins`

Validates and persists a check-in.

Response 201:

```json
{
  "id": "uuid",
  "created_at": "ISO8601",
  "check_in": {}
}
```

### POST `/v1/recommendations`

Input: `CheckIn`

Response 200:

```json
{
  "practice_id": "body_awareness",
  "duration_minutes": 5,
  "guidance_density": 0.65,
  "reason_codes": ["goal_overthinking", "high_mental_activity", "high_stress"],
  "recommendation_version": "1"
}
```

This endpoint must work without database availability when called through the domain service in unit tests.

### POST `/v1/sessions`

Input:

```json
{
  "check_in_id": "uuid",
  "recommendation": {}
}
```

Response 201 includes:

- session id
- selected protocol
- rendered stage plan
- status `created`

### POST `/v1/sessions/{session_id}/feedback`

Persists feedback and marks the session completed or abandoned according to request data.

### GET `/healthz`

Must return 200 without requiring an external AI provider.

---

## 8. Persistence

Use PostgreSQL.

Minimum tables:

- check_ins
- sessions
- session_feedback

For Program001, recommendations may be embedded in the session row as JSONB or normalized separately; choose the simpler design unless a concrete query requirement justifies normalization.

Requirements:

- UUID primary keys
- UTC timestamps
- Alembic migrations
- no PII required for guest sessions
- future `user_id` must be nullable initially

Do not add Redis in Program001 unless tests demonstrate a real need.

---

## 9. Guest-first identity

The first vertical slice must support anonymous/guest usage.

Do not block meditation behind registration.

Architecture requirement:

- session/check-in records may exist without an account
- later account linking must be possible via nullable `user_id`
- do not generate a fake email or fake identity for guests

Authentication implementation may be deferred, but domain models must not assume every session has a registered account.

---

## 10. Flutter implementation

Create a minimal but functional Flutter app.

Required screens:

1. Welcome
2. Check-in
3. Recommendation
4. Session player
5. Feedback
6. Session history placeholder or basic local list

### Welcome

Primary CTA:

`Start a session`

Secondary path may say:

`Continue as guest`

No forced registration.

### Check-in

Collect:

- goal
- stress
- energy
- mental activity
- sleepiness
- available time
- experience

Use accessible controls. Do not require camera, microphone, location, or health permissions.

### Recommendation

Show:

- public practice title
- duration
- concise reason in user-friendly language
- Start button

Do not display internal source mappings by default.

### Session player

Program001 does not require production TTS.

Implement a deterministic session timeline from protocol stages with:

- progress
- stage text
- pause/resume
- end session

Audio/TTS integration must be behind an interface so later providers can be added without changing the session domain.

### Feedback

Collect after-state/helpfulness and completion.

---

## 11. Platform abstraction

Define interfaces/adapters for store-sensitive features even if Program001 implementations are stubs.

Required conceptual interfaces:

```text
AuthProvider
BillingProvider
TTSProvider
SecureStorageProvider
NotificationProvider
HealthProvider (disabled/deferred)
```

Do not request mobile permissions for deferred features.

No Apple or Google store secret is committed to the repository.

---

## 12. Compliance requirements

Use `compliance/data-inventory.v1.yaml` as source of truth.

Create/update `compliance/permissions.v1.yaml` so Program001 declares:

- camera: false
- microphone: false
- location: false
- HealthKit: false
- Health Connect: false
- notifications: optional, preferably false for first slice

Create public route placeholders or static pages for:

- `/privacy`
- `/terms`
- `/support`
- `/delete-account`

For guest-only Program001, delete-account may explain that guest data deletion is handled by local/session identifier until accounts exist; do not falsely claim a backend feature that is not implemented.

No health/wellness data may be marked for advertising use.

---

## 13. OCI deployment design

The existing `infra/docker-compose.yml` is the baseline.

Program001 deployment services:

- api
- postgres
- reverse proxy only when needed

Target resource ceilings:

- API container <= 768 MB RAM
- PostgreSQL <= 1.5 GB RAM
- no resident LLM
- no resident TTS model required for first vertical slice

Build images for ARM64 compatibility.

Backend container must run as non-root if practical.

Secrets must come from environment/runtime secret injection, not Git.

---

## 14. CI

Create `.github/workflows/ci.yml`.

Required jobs:

### Backend

- install Python dependencies
- lint
- type check where configured
- run pytest
- validate YAML knowledge files
- validate OpenAPI document

### Flutter

- `flutter pub get`
- `flutter analyze`
- `flutter test`

If Flutter bootstrap cannot be completed in the environment used by the coding agent, the agent must still create valid project files and document the exact unresolved environment limitation instead of weakening the acceptance criteria silently.

No deployment to OCI from CI in Program001 unless credentials already exist through secure repository/environment configuration.

---

## 15. Testing contract

### 15.1 Recommendation unit tests

At minimum:

1. `goal=overthinking, mental_activity=9, stress=8` → `body_awareness`
2. `goal=overthinking, mental_activity=9, stress=3` → `thought_observation`
3. `goal=sleep` → `body_awareness`
4. `goal=focus, sleepiness=8` → `body_awareness`
5. `goal=focus, sleepiness=2` → `breath_awareness`
6. `goal=stress, stress=9` → `body_awareness`
7. `goal=stress, stress=2, experience=experienced` → `open_awareness`
8. `goal=general, beginner` → `breath_awareness`
9. `goal=general, experienced` → `open_awareness`
10. same normalized input repeated 100 times → identical recommendation output

### 15.2 Duration tests

Verify every `available_minutes` / experience combination.

### 15.3 Validation tests

Reject:

- stress < 0
- stress > 10
- unsupported goal
- unsupported duration
- unsupported experience

### 15.4 API tests

At minimum:

- healthz returns 200
- recommendation returns 200 and schema-valid JSON
- invalid check-in returns 422
- session can be created from valid recommendation
- feedback can be attached to an existing session
- unknown session feedback returns 404

### 15.5 Knowledge validation

Tests must fail if:

- recommendation returns unknown practice_id
- protocol references unknown practice_id
- protocol supports no declared duration
- guidance density falls outside practice/protocol range

---

## 16. Non-functional requirements

### Performance

On OCI-class hardware, deterministic recommendation p95 should be comfortably below 100 ms excluding network latency.

### Availability

The API must boot and `/healthz` must function without any AI API key.

### Security

- no credentials in source
- parameterized DB access via ORM
- bounded input sizes
- no arbitrary prompt passthrough in Program001

### Privacy

- no advertising use of wellness data
- no unnecessary mobile permissions
- guest-first collection minimization

### Maintainability

- modular monolith
- pure domain recommendation logic
- versioned rules and knowledge files
- provider interfaces for external AI/TTS/billing

---

## 17. Explicit non-goals

Do NOT implement in Program001:

- production voice cloning
- celebrity voices
- real-time generative ambience
- wearable integrations
- HRV interpretation
- diagnosis
- therapy workflows
- B2B employee analytics
- creator marketplace
- multilingual localization
- Kubernetes
- microservices decomposition
- vector database unless a tested requirement appears
- paid external LLM dependency for core recommendation

---

## 18. Engineering execution order for Claude

Claude should execute in this order unless a concrete repository dependency requires minor reordering:

### Phase A — audit

1. Read README.md
2. Read docs/PROGRAM001.md
3. Read this SDD
4. Read api/openapi.v1.yaml
5. Read knowledge/practices.v1.yaml
6. Read compliance/data-inventory.v1.yaml
7. Read infra/docker-compose.yml
8. Inspect current branch and repository status

Do not overwrite valid existing work.

### Phase B — backend bootstrap

1. Create Python project
2. FastAPI app
3. Pydantic models
4. deterministic recommendation engine
5. knowledge loader
6. tests
7. PostgreSQL models/migration
8. session/feedback API

### Phase C — protocol engine

1. Create protocols.v1.yaml
2. validation loader
3. render deterministic stage timeline
4. tests

### Phase D — Flutter bootstrap

1. Create app
2. API client
3. check-in screen
4. recommendation screen
5. session timeline/player
6. feedback screen
7. widget/unit tests

### Phase E — compliance and CI

1. permissions manifest
2. privacy/terms/support/delete placeholders
3. GitHub Actions CI
4. Docker build validation
5. OpenAPI consistency

### Phase F — evidence

Before declaring success, Claude must provide:

- exact files changed
- tests executed
- test results
- lint/analyze results
- unresolved issues
- next engineering slice

Do not claim a command/test passed unless it was actually executed.

---

## 19. Definition of Done

Program001 implementation is DONE only when all of the following are true:

- backend starts locally
- `/healthz` returns 200
- deterministic recommendation engine passes all required tests
- knowledge/protocol cross-validation passes
- check-in → recommendation → session → feedback works through API tests
- PostgreSQL migration exists
- Docker image builds for the backend
- Flutter project exists and statically analyzes successfully, or a concrete toolchain limitation is documented with all source work completed
- no prohibited V1 mobile permissions are introduced
- CI workflow exists
- no secret is committed
- documentation is synchronized with implementation

A partial implementation must be reported as PARTIAL, not DONE.

---

## 20. Claude execution instruction

Work directly in the repository on the current Program001 branch. Prefer small coherent commits. Do not stop after planning. Implement until the Definition of Done is reached or a real external dependency blocks progress.

When encountering a defect, fix it if it is within the Program001 scope. Do not ask for confirmation for routine engineering decisions that are already constrained by this SDD.

Preserve these product invariants:

1. wellness, not medical diagnosis/treatment
2. source-grounded practice intelligence, non-sectarian user presentation
3. deterministic core recommendation independent of external AI
4. guest-first usability
5. OCI A1 resource discipline
6. Apple/Google store-sensitive capabilities deferred or isolated
7. individual-first commercialization with future company migration support
8. no false test/deployment claims
