# Program001 — US-first Adaptive Meditation Foundation

## Objective

Create the smallest store-ready technical foundation that can support a real paid meditation product on iOS and Android while fitting the existing OCI A1 capacity.

## Product boundary

V1 solves four user jobs:

- Calm stress
- Quiet overthinking
- Improve focus
- Prepare for sleep

The application does not diagnose, treat, or claim to cure medical or psychiatric conditions.

## Vertical slice

`check-in → state vector → protocol selection → session plan → session completion → outcome feedback`

### Check-in fields

- goal
- stress 0–10
- energy 0–10
- mental_activity 0–10
- sleepiness 0–10
- available_minutes
- experience_level

### Practice families

Public labels:

- Breath Awareness
- Body Awareness
- Feeling Tone
- Thought Observation
- Kindness Practice
- Open Awareness
- Mindful Walking

Internal source mapping is retained separately and is not required as user-facing religious terminology.

## Target architecture

### Client

Flutter is the target client framework.

Adapters must isolate:

- authentication
- billing
- secure storage
- notifications
- future health integrations

### Backend

- Python / FastAPI
- PostgreSQL
- background worker only where necessary
- REST/JSON initially
- Docker Compose deployment
- Caddy or equivalent reverse proxy

### OCI resource budget

Target host: ARM64 A1 Flex, 2 OCPU, 12 GB RAM, 200 GB storage.

No Kubernetes, Kafka, Elasticsearch, service mesh, or large local LLM in V1.

### AI boundary

`AIProvider` and `TTSProvider` are interfaces. The protocol engine must work without a generative provider. AI may rewrite/personalize a selected structured protocol but cannot silently replace its practice family, safety constraints, or duration envelope.

## Store-first constraints

V1 intentionally excludes:

- HealthKit
- Health Connect
- Garmin
- camera posture detection
- biometric emotion inference
- creator voice cloning
- medical claims

Required from V1:

- privacy policy route
- terms route
- account deletion path
- data export design
- AI output reporting path
- safety routing before free generation
- Apple/Google billing abstraction
- restore-purchase support design
- machine-readable data inventory

## Individual-first commercialization

Initial developer/seller identity is individual, not a company. Company formation is deferred until validated commercial traction or contractual/liability needs justify it.

Architecture must keep brand/product identifiers separate from legal-owner identity to support later migration.

## Acceptance criteria

Program001 is complete when:

1. Repository layout exists for app, API, domain, knowledge, compliance, infra and tests.
2. Practice protocol and user-state schemas are versioned.
3. A deterministic state-to-practice selector is specified and testable.
4. API contract covers check-in, recommendation, session creation and feedback.
5. OCI Docker Compose deployment specification fits the resource budget.
6. Compliance inventory declares V1 data and permissions.
7. iOS/Android store-sensitive capabilities are isolated behind adapters or explicitly deferred.
8. CI design includes backend tests, schema validation and Flutter checks.

## Implementation

The acceptance criteria above are implemented on `program001/foundation`.
Per-item results, the exact verification commands, and the known gaps are in
[PROGRAM001_STATUS.md](PROGRAM001_STATUS.md).

Two points where the implementation is narrower than this document:

- The practice families list here includes Mindful Walking. V1 ships the six
  families in `knowledge/practices.v1.yaml` and `knowledge/protocols.v1.yaml`;
  the SDD's initial practice IDs, which are authoritative for this round, do not
  include it.
- `kindness` has an executable protocol but no rule selects it yet. This is the
  SDD's rule set as written, and the reachable set is pinned by a test so it
  stays visible.
