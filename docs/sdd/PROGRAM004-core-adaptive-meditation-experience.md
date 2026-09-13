# Software Design Document (SDD)

## Program004 — Core Adaptive Meditation Session Engine, Audio Runtime, Voice Delivery and Test Isolation Architecture

**Task ID:** `PROGRAM004_SDD_CORE_ADAPTIVE_MEDITATION_SESSION_ENGINE_AUDIO_RUNTIME_AND_VOICE_DELIVERY`
**Type:** SDD only. No implementation is authorised by this document.
**Branch:** `program004/core-adaptive-meditation-sdd`

---

## 0. Governing principle

Program004 is not an audio feature. It is the transition from an application that
can *recommend* a meditation to one in which a person can actually *complete*
one: start it, hear it, pause it, be interrupted by a phone call, come back, and
finish — reliably enough to do it daily.

Every decision below is judged against that outcome, not against abstraction
elegance. An architecture that is beautiful and produces no session anyone wants
to sit through has failed.

---

## 1. Baseline: verified remote evidence

Checked before authoring, not assumed.

| Fact | Value |
|------|-------|
| Remote `main` | `ec82f883701e6e7ae4fa94075c6bf541f70ae75c` |
| PR #3 state | **OPEN**, `MERGEABLE`, merge state `CLEAN`, 0 comments |
| PR #3 head | `a75b6ca1ccde1d2592dc588e9597ee93d0fadd7d` |
| PR #3 merged | **no** — `mergedAt` is null, no merge commit |
| Latest CI on `program003/store-readiness` | run **34668439627** (push) and **34668441620** (pull_request) at `a75b6ca1`, **all six jobs success** |
| Worktree | clean |
| Program003 SDD | `docs/SDD_PROGRAM003.md` present |
| Program003 status | `docs/PROGRAM003_STATUS.md` present |
| Program003 compliance machinery | all seven manifests and four gate scripts present |

### 1.1 Program003 disposition

```text
PROGRAM003_IMPLEMENTED_CI_GREEN_PENDING_REMOTE_CLOSURE
```

Program003 is implemented and green on hosted CI, and is **not remotely closed**.
PR #3 is open. Nothing in this document treats Program003 as merged, and no
Program003 implementation file is modified to produce this SDD.

### 1.2 Branch base, and why it is not `main`

This branch is cut from `program003/store-readiness` (`a75b6ca1`), not from
`main` (`ec82f88`).

Program004 extends machinery that exists only on the Program003 branch:
`scripts/check_compliance_consistency.py`, the Apple and Google mappings, the
third-party SDK inventory and `PrivacyInfo.xcprivacy`. An SDD that specified
extensions to files absent from its own branch would be unverifiable.

**Recorded dependency:** Program004 implementation must not merge before PR #3.
If PR #3 is closed unmerged, this SDD requires revision, because its compliance
integration points would no longer exist.

---

## 2. What already exists, and what is missing

Being precise about the starting point, because the gap is smaller than "build
an audio engine" suggests and larger than "add TTS" suggests.

**Already built (Program001–003):**

- a deterministic recommendation engine with versioned rule sets;
- `SessionPlan` / `RenderedStage` — an exact second-by-second stage allocation
  whose durations always sum to the session length;
- `sessions` persistence with `created → started → completed | abandoned`;
- guest identity in secure storage, with deletion and export;
- deterministic experiment assignment with assignment/exposure separation;
- outcome evidence and an offline report;
- compliance consistency enforced in CI across five documents.

**Missing, and the subject of this program:**

- no notion of *speech*, *silence*, *bell* or *ambience* as distinct things —
  a stage is a prompt string plus a cue count;
- no audio of any kind;
- no playback runtime, so no pause, resume, interruption or recovery;
- no content versioning, so a completed session stops being reproducible the
  moment a prompt template is edited;
- no per-segment event record, so "they abandoned it" cannot answer "where";
- a test suite that cannot run twice concurrently against one database.

The existing `RenderedStage` is the right shape one level too coarse. Program004
subdivides a stage into typed segments rather than replacing the planner.

---

## 3. System architecture

### 3.1 Component diagram

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                              BACKEND                                      │
│                                                                           │
│  ┌────────────────┐   intent    ┌──────────────────┐                      │
│  │ Recommendation │───────────▶ │ Session Planner  │                      │
│  │    Engine      │             │  (deterministic) │                      │
│  │ (Program002)   │             └────────┬─────────┘                      │
│  └────────────────┘                      │ reads                          │
│         ▲                                ▼                                │
│         │                       ┌──────────────────┐                      │
│         │                       │  Content Layer   │  immutable,          │
│         │                       │ session_definition│  versioned          │
│         │                       └────────┬─────────┘                      │
│         │                                │ produces                       │
│         │                                ▼                                │
│         │                       ┌──────────────────┐                      │
│         │                       │  SessionPlan v2  │  typed segments,     │
│         │                       │  + plan_hash     │  frozen at creation  │
│         │                       └────────┬─────────┘                      │
│         │                                │                                │
│  ┌──────┴───────┐   ┌──────────────┐    │    ┌─────────────────────────┐ │
│  │  Experiment  │   │   Outcome    │◀───┤    │  Render Coordinator     │ │
│  │  assignment  │   │    Layer     │    │    │  (content-addressed)    │ │
│  │  / exposure  │   └──────────────┘    │    └───────────┬─────────────┘ │
│  └──────────────┘                        │                │               │
│                                          │                ▼               │
│                                          │    ┌─────────────────────────┐ │
│                                          │    │  SpeechRenderer (port)  │ │
│                                          │    └───────────┬─────────────┘ │
│                                          │                │ adapters      │
│                                          │    ┌───────────┴─────────────┐ │
│                                          │    │ pregenerated │ (future  │ │
│                                          │    │   provider   │  human)  │ │
│                                          │    └─────────────────────────┘ │
└──────────────────────────────────────────┼────────────────────────────────┘
                                           │ plan + render manifest
                     ═══════════════════════╪═══════════════════════════════
                                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            FLUTTER CLIENT                                 │
│                                                                           │
│  ┌────────────────────┐      ┌──────────────────────────────────────────┐│
│  │  Session Prepare   │─────▶│          Playback Runtime                ││
│  │  (fetch + warm     │      │  state machine · monotonic clock ·       ││
│  │   the audio cache) │      │  segment scheduler · audio focus         ││
│  └────────────────────┘      └───────┬──────────────────────┬───────────┘│
│           │                          │                      │            │
│           ▼                          ▼                      ▼            │
│  ┌────────────────┐     ┌─────────────────────┐   ┌──────────────────┐  │
│  │  Audio Cache   │     │  AudioSource (port) │   │  Event Journal   │  │
│  │ content-addr.  │     └──────────┬──────────┘   │  (append-only,   │  │
│  └────────────────┘                │ adapters     │   flushed to API)│  │
│                        ┌───────────┴───────────┐  └──────────────────┘  │
│                        │ cached │ device TTS   │                        │
│                        │ file   │ (fallback)   │                        │
│                        └────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────────┘
```

**The boundary that matters:** the Playback Runtime knows about segments,
durations and audio handles. It does not know what a practice is, which rule set
chose it, which experiment arm this guest is in, or that a language model exists.
Everything above the dashed line is decided before a single sample plays.

### 3.2 Recommendation → playback sequence

```text
Client                 API                  Planner        Renderer      Cache
  │                     │                      │              │            │
  ├─ POST /recommendations ──▶                 │              │            │
  │ ◀── recommendation + variant ──            │              │            │
  │                     │                      │              │            │
  ├─ POST /sessions ───▶│                      │              │            │
  │                     ├─ re-derive rec ─────▶│              │            │
  │                     ├─ freeze definition ─▶│              │            │
  │                     ├─ build typed plan ──▶│              │            │
  │                     ├─ for each speech segment:           │            │
  │                     │     render_key = hash(text,voice,…) │            │
  │                     ├──────────────────────┼─ lookup ────▶│            │
  │                     │                      │  hit  ◀──────┤            │
  │                     │                      │  miss → render + store    │
  │ ◀── session + plan + render manifest ──────┤              │            │
  │        (audio URLs + durations + hashes)   │              │            │
  │                     │                      │              │            │
  ├─ prepare: fetch uncached audio, verify hashes ───────────────────────▶ │
  │   (or fall back to device TTS per segment)                             │
  │                     │                      │              │            │
  ├─ state: ready       │                      │              │            │
  ├─ user taps start ──▶ runtime plays segment 0 …                         │
  │                     │                      │              │            │
  ├─ POST /sessions/{id}/events (batched) ────▶│  append-only journal      │
  │                     │                      │              │            │
  ├─ POST /sessions/{id}/feedback ────────────▶│  outcome layer            │
```

Note what the sequence does **not** contain: no call to a voice provider while
the user is waiting to begin, and no provider call at all on a cache hit.

---

## 4. Component contracts

### A. Recommendation Engine — unchanged

Emits intent: practice, goal, duration, guidance density, reason codes, version
triple, explanation variant. It gains no knowledge of audio. Its output is an
input to planning and nothing more.

### B. Session Planner

`RecommendationIntent + SessionDefinition → SessionPlan(v2)`

Pure, deterministic, no I/O beyond reading frozen content. Same intent and same
definition version always produce the same plan and therefore the same
`plan_hash`. This is the Program002 determinism contract extended one level down.

### C. Content Layer

Guidance content becomes a first-class versioned entity rather than a template
string read at render time.

| Concept | Meaning |
|---------|---------|
| `content_source` | `authored` \| `generated` \| `localized` |
| `definition_version` | monotonically increasing per template |
| `locale` | BCP-47 |
| `frozen` | once referenced by a session, immutable forever |

**Historical reproducibility rule:** a session row references a
`session_definition_id` **and** stores its own `plan_hash`. Editing a prompt
creates a new definition version; it never mutates one. A session completed in
March remains interpretable in December because the exact words it used are
still addressable.

Today the prompts live in `knowledge/protocols.v2.yaml` and are read live. That
is fine for a recommendation but not for an audit trail, and it is the reason
this layer exists.

### D. Voice / Audio Rendering Layer

A port with a deliberately small surface:

```text
SpeechRenderer
  render(RenderRequest) -> RenderedAudio
  capabilities() -> RendererCapabilities

RenderRequest   : text, locale, voice_id, speaking_style, render_version
RenderedAudio   : bytes | uri, duration_ms (measured), codec, render_key
Capabilities    : offline_capable, deterministic, supports_ssml, voices[]
```

`RenderRequest` carries **no guest identifier, no session id, no experiment
arm, no free text the user wrote**. It carries product-authored guidance and the
parameters needed to say it. That constraint is what keeps the privacy delta of
adding a provider close to nothing, and it is testable.

### E. Playback Runtime

Owns: state machine, monotonic clock, segment scheduling, audio focus, the event
journal. Owns nothing else. It receives a plan and a render manifest and plays
them.

### F. Session Persistence

The minimum to resume and to account: which session, which plan, which segment
boundary was last confirmed, and an append-only event log.

### G. Outcome Layer

Consumes completed and abandoned facts. Already exists; gains richer inputs
(where in the session the user stopped) without gaining any control over
playback.

---

## 5. Session state machine

### 5.1 States

```text
        ┌─────────┐
        │ created │  plan frozen, nothing fetched
        └────┬────┘
             │ prepare()
             ▼
      ┌────────────┐  fetch + verify audio, or confirm TTS fallback
      │ preparing  │──────────────┐
      └─────┬──────┘              │ unrecoverable
            │ all segments        ▼
            │ resolvable      ┌────────┐
            ▼                 │ failed │
       ┌─────────┐            └────────┘
       │  ready  │◀──────────────┐
       └────┬────┘               │ recover()
            │ start()            │
            ▼                    │
       ┌─────────┐  pause()  ┌────────┐
   ┌──▶│ playing │──────────▶│ paused │
   │   └────┬────┘◀──────────└───┬────┘
   │        │      resume()      │
   │        │ audio focus lost   │ end()
   │        ▼                    │
   │  ┌─────────────┐            │
   └──│ interrupted │            │
 focus└──────┬──────┘            │
 regained    │ end() / timeout   │
             ▼                   ▼
        ┌───────────┐      ┌───────────┐
        │ completed │      │ abandoned │
        └───────────┘      └───────────┘
```

`backgrounded` is deliberately **not** a state. On both platforms a meditation
session must keep playing when the screen locks — that is the product. Backgrounding
is an environment fact, recorded as an event, not a playback state. Modelling it
as a state would imply playback stops, which would be a bug.

### 5.2 Transition table

| From | Event | To | Notes |
|------|-------|----|-------|
| `created` | `prepare` | `preparing` | |
| `preparing` | `resolved` | `ready` | every segment has audio or an accepted fallback |
| `preparing` | `unresolvable` | `failed` | see failure taxonomy |
| `ready` | `start` | `playing` | **exposure boundary for session experiments** |
| `playing` | `pause` (user) | `paused` | |
| `playing` | `focus_lost` | `interrupted` | call, other app, route loss |
| `playing` | `timeline_end` | `completed` | |
| `playing` | `runtime_error` | `failed` | |
| `paused` | `resume` | `playing` | |
| `paused` | `end` (user) | `abandoned` | |
| `interrupted` | `focus_regained` | `paused` | **never auto-resumes** |
| `interrupted` | `end` / expiry | `abandoned` | |
| `failed` | `recover` | `ready` | only if the plan is still valid |
| `completed` / `abandoned` | any | — | terminal |

**Impossible transitions**, asserted in tests: `created → playing` (nothing is
prepared); `ready → completed` (nothing was heard); `completed → playing`;
`completed → abandoned` and the reverse; `abandoned → completed`; any transition
out of a terminal state.

`interrupted → paused` rather than `interrupted → playing` is a product decision,
not a technical one. Audio resuming by itself after a phone call, possibly on a
speaker, in a room with other people, is a worse failure than a session that
waits.

### 5.3 Named scenarios

| Scenario | Behaviour |
|----------|-----------|
| App killed during silence | Journal holds the last confirmed segment boundary. On relaunch, offer resume from that boundary. |
| App killed during speech | Resume restarts **that segment from its beginning**. Never resume mid-utterance: half a sentence is worse than a repeated one. |
| Phone call | Focus loss → `interrupted`. On focus return → `paused`, user resumes. |
| Bluetooth disconnects | Route-change event. If audio is now on the speaker, treat as focus loss → `interrupted`. Suddenly broadcasting a meditation to a room is a privacy event, not a convenience. |
| Route change (headphones in) | Continue; record event. |
| Pause then lock | Stays `paused`. No timer runs. |
| Resume after minutes | Allowed while the run is not terminal. Elapsed is playback time, not wall time. |
| Audio asset unavailable | Per-segment fallback (see §9.4). If no fallback, `failed` with `AUDIO_ASSET_MISSING`. |
| TTS render fails | Fallback chain; if exhausted, `failed` with `RENDER_UNAVAILABLE`. |
| Network lost mid-session | **No effect.** A prepared session is fully local. |
| Definition changed server-side after start | No effect. The run is pinned to `plan_hash`. |
| Duplicate completion | Idempotent (§5.4). |
| Rapid play/pause | Debounced by command sequence number; out-of-order commands dropped. |

### 5.4 Idempotency

Every state-changing client call carries a `command_id` (client-generated UUIDv4)
and a monotonically increasing `sequence` per run.

- Replaying a `command_id` returns the **same** result without re-applying it.
- A `sequence` lower than the highest applied is **dropped**, not applied.
- `complete` and `abandon` are terminal and idempotent: a second call returns the
  existing terminal state rather than an error, because a client retrying after a
  flaky network is doing the right thing and should not be punished for it.

---

## 6. Timeline semantics

### 6.1 Typed segments

```text
SessionPlan(v2)
  plan_hash          : sha256 of the canonical serialised plan
  definition_id      : frozen content version
  total_seconds      : the invariant
  segments[]         : ordered, contiguous

Segment = Speech | Silence | Bell | AmbienceStart | AmbienceStop | Marker

Speech       : text, render_key, estimated_ms, min_ms, transcript_id
Silence      : target_ms, min_ms, elastic: bool
Bell         : bell_id, asset_key, duration_ms
AmbienceStart: loop_id, asset_key, gain
AmbienceStop : fade_ms
Marker       : marker_id            (analytics / experiment anchor, silent)
```

Ambience start/stop are separate segments rather than a property of a span so
that the timeline stays a flat ordered list. A nested span model would make every
seek and recovery calculation a tree walk for no product gain.

### 6.2 Example timeline

```text
00:00.000  Bell(open)                        2.0s
00:02.000  Speech("Settle into a position…")  ~14s   est, elastic follows
00:16.000  Silence(target 20s, elastic)       20.0s
00:36.000  Speech("Find where the breath…")  ~18s
00:54.000  Silence(target 45s, elastic)       45.0s
01:39.000  Marker(experiment_anchor_A)         0.0s
…
09:44.000  Speech("Widen your attention…")   ~12s
09:56.000  Bell(close)                        2.0s
10:00.000  END — total_seconds invariant holds
```

### 6.3 Clock

- **Elapsed playback time uses a monotonic source** (`Stopwatch` / `elapsedRealtime`).
  Wall clock is used only for audit timestamps on journal events. A user changing
  timezone or an NTP correction mid-session must not shorten their meditation.
- Pause stops the monotonic accumulator; resume restarts it. Elapsed is the sum
  of played intervals, never `now - started_at`.
- The scheduler is **event-driven, not polled**: the next segment is armed by the
  completion callback of the current one, with a timer only for silence.

### 6.4 Duration variance — the central problem

A speech segment's real duration is not knowable at planning time when the
renderer is device TTS, and differs from the estimate even for fixed assets
across codecs.

**Resolution: elastic silence absorbs the variance; total duration is the
invariant.**

```text
planned:   speech(est 14.0s) → silence(target 20.0s)
actual:    speech(     16.3s) → silence(     17.7s)
                                        └── absorbed −2.3s, floor min_ms respected
```

Rules:

1. Each silence has `target_ms` and `min_ms`. Elastic silences may shrink to
   `min_ms` and grow without bound within the session total.
2. After each speech segment the scheduler recomputes the remaining budget:
   `remaining = total_ms − elapsed_ms`, and redistributes across the remaining
   elastic silences in proportion to their targets.
3. If cumulative overrun would push a silence below `min_ms`, the deficit
   cascades to later elastic silences. If the whole remaining budget is
   exhausted, the session **ends early at the closing bell** rather than
   truncating speech mid-word — and the event journal records
   `TIMELINE_COMPRESSED` so it is visible, not silent.
4. **Drift tolerance:** ±2% of total, or ±3s, whichever is larger. Beyond that,
   emit `TIMELINE_DRIFT_EXCEEDED` telemetry. This is an observability threshold,
   not a user-visible failure.

Measured durations from the renderer are written back to the cache, so a
pre-generated corpus becomes *more* accurately planned over time.

### 6.5 Seek

MVP: **no scrubbing.** Permitted: skip-to-next-segment backwards only (replay the
current speech segment). Forward seek is deliberately withheld — a meditation the
user can fast-forward through is a recording, not a practice, and the outcome
data would stop meaning anything.

### 6.6 Completion

A session is `completed` when the final segment's end is reached with
`elapsed_ms >= total_ms − drift_tolerance`. Reaching the last segment by
compression still completes. Anything else that ends the run is `abandoned`, and
`completion_ratio` (already consumed by the outcome layer) is
`elapsed_ms / total_ms`.

---

## 7. Adaptive behaviour boundary

### 7.1 Deterministic adaptation — in scope

Varies by `StateVector`, computed by pure functions, reproducible from
`(state_fingerprint, rule_set_version, definition_version)`:

practice selection · duration · guidance density · wording variant · silence
target length · optional ambience · opening/closing style.

Everything Program004 ships is in this class.

### 7.2 Generative adaptation — extension points only

```text
generator → candidate content → ContentValidator → frozen definition version
                                      │
                                      ├─ prohibited-claim lint (§11)
                                      ├─ length / structure constraints
                                      ├─ locale + reading-level checks
                                      └─ human approval gate
                                                 │
                                                 ▼
                                         planner may now use it
```

Two hard rules:

1. **Generated content never enters a plan without passing validation and being
   frozen as a version.** The planner cannot see unvalidated text.
2. **The playback runtime never invokes a model.** It has no client, no
   credential and no code path to one. This is enforceable by a test that
   asserts the playback package imports nothing from the AI package — the same
   shape as the existing test that asserts the recommendation engine opens no
   socket.

---

## 8. Voice strategy decision

### 8.1 The decisive property: the corpus is tiny and static

Seven protocols × four or five stages ≈ **33 distinct utterances**, with a single
numeric placeholder. Not thousands of hours of narration. Every architecture
question below is downstream of that.

### 8.2 Decision matrix

Scores: ●●● good · ●● acceptable · ● poor

| Criterion | Device-native TTS | Packaged prerecorded | Server pre-generated TTS | Real-time cloud TTS |
|---|---|---|---|---|
| Voice quality | ●● | ●●● | ●●● | ●●● |
| Latency to first audio | ●●● instant | ●●● instant | ●●● cached | ● network per utterance |
| Offline | ●●● | ●●● | ●●● after prepare | ● none |
| Privacy exposure | ●● OS-dependent | ●●● none | ●●● no user data in request | ● per-session network egress |
| Vendor data retention | n/a (OS) | none | one-off at build | ongoing |
| Cost / completed session | £0 | £0 | ~£0 (cache hit) | material, recurring |
| Cache-ability | n/a | n/a | ●●● | ●● |
| Localization cost | ●●● free | ● re-record | ●● re-render | ●● |
| Deterministic replay | ● varies by OS/device | ●●● | ●●● | ●● |
| App Store declaration impact | none | none | none | possible new third party |
| Google Data Safety impact | none | none | none | possible new third party |
| SDK footprint | small plugin | none | none (HTTP) | vendor SDK or HTTP |
| Network dependency | none | none | prepare-time only | hard |
| Provider lock-in | none | none | low (re-render) | high |
| Failure recovery | OS fallback | n/a | fall back to device TTS | no fallback |
| External credential needed | **no** | voice talent | vendor account | vendor account |

### 8.3 Cost model

For any paid synthesis, at a representative neural-TTS price of ~$16 per million
characters:

| Quantity | Value |
|---|---|
| Corpus | ~33 utterances × ~200 chars ≈ 6,600 chars |
| Per voice × locale | ~6,600 chars ≈ **$0.11** |
| 6 voices × 2 locales | ~79,000 chars ≈ **$1.27, one-off** |
| Cost / rendered minute | ~$0.016 |
| Cost / 10-min completed session, cache miss | ~$0.11 (first ever render only) |
| **Cost / 10-min completed session, cache hit** | **$0.00** |
| **Cost / 1,000 completed sessions** | **$0.00 generation**; storage + egress only |
| Cost / MAU | ≈ storage + egress; generation amortises to zero |

Storage: ~33 × 6 × 2 × ~150 kB ≈ **60 MB** total. Egress dominates, and only on
first fetch per device.

The architectural point is not that cloud TTS is cheap. It is that **a bounded
static corpus turns synthesis into a build-time cost rather than a runtime one**,
and an architecture that re-synthesises the same sentence per session has thrown
that away.

### 8.4 Decision

**Provider-neutral runtime. First shipped provider: device-native TTS.
Second provider, behind the same port: server-side pre-generated audio.
No real-time cloud synthesis, ever, on the playback path.**

Device-native first because it is the only option with **no external credential
dependency** — it can ship while the brand, the Apple account and the vendor
account are all unresolved, which is exactly the situation §24 describes. It is
offline, costs nothing, and localises free.

Its two real weaknesses are addressed rather than ignored: quality is the reason
pre-generated audio is designed in from day one as a drop-in second adapter; and
**non-determinism of duration** is precisely what §6.4's elastic silence exists
to absorb.

**Documented risk:** on Android, the system TTS engine may perform network
synthesis outside our control. The app cannot observe this. It must therefore be
disclosed in the privacy policy as an OS-level behaviour, and it is an argument
for making pre-generated audio the default as soon as a vendor account exists.
On iOS, `AVSpeechSynthesizer` uses on-device voices for the compact set.

### 8.5 Prohibited in any render request

No guest identifier. No session id. No experiment arm. No history. No free-text
journal or feedback note. No device identifier. Enforceable as a unit test over
the serialised `RenderRequest`.

---

## 9. Audio caching architecture

### 9.1 Content-addressed key

```text
render_key = sha256(
    normalize(text)      ‖ 0x00 ‖
    locale               ‖ 0x00 ‖
    voice_id             ‖ 0x00 ‖
    speaking_style       ‖ 0x00 ‖
    provider_id          ‖ 0x00 ‖
    provider_version     ‖ 0x00 ‖
    render_version
)
```

`normalize` = NFC, collapse internal whitespace, strip leading/trailing space.
Field separators prevent the concatenation ambiguity where two different field
splits hash identically.

Derived from **render inputs only**. Not from guest identity, session id or
timestamp. Two guests on one device who receive the same guidance share one file,
which is both a storage win and a privacy property: the cache reveals which
*content* was fetched, never *who* fetched it.

### 9.1b Audio provider and data flow

```text
                        ┌──────────────────────────────────────────┐
   PLAN TIME            │            Render Coordinator            │
   (backend)            │   for each Speech segment:               │
                        │     render_key = sha256(text‖locale‖…)   │
                        └───────────────┬──────────────────────────┘
                                        │ lookup by render_key
                                        ▼
                        ┌──────────────────────────────────────────┐
                        │      audio_renders  (content-addressed)  │
                        │   render_key · duration_ms · sha256 · uri│
                        └───────┬──────────────────────┬───────────┘
                          hit   │                      │  miss
                                │                      ▼
                                │      ┌───────────────────────────────┐
                                │      │   SpeechRenderer  (PORT)      │
                                │      │   render(RenderRequest)       │
                                │      └───────┬───────────────┬───────┘
                                │              │               │
                                │   ┌──────────▼─────┐  ┌──────▼────────────┐
                                │   │ pre-generated  │  │ future: human     │
                                │   │ vendor adapter │  │ voice asset import│
                                │   └────────────────┘  └───────────────────┘
                                │        │ product-authored text only
                                │        │ NO guest id · NO session id
                                │        │ NO experiment arm · NO free text
                                ▼        ▼
                        ┌──────────────────────────────────────────┐
                        │   render manifest: [render_key, uri,     │
                        │   duration_ms, sha256] per segment       │
                        └───────────────┬──────────────────────────┘
   ═════════════════════════════════════╪══════════════════════════════════
   PREPARE TIME                         ▼
   (client)             ┌──────────────────────────────────────────┐
                        │       Session Prepare / cache warm       │
                        └───────┬──────────────────────┬───────────┘
                          resident│                    │ fetch + verify sha256
                                │                      ▼
                        ┌───────▼──────────────────────────────────┐
                        │  Local audio cache (content-addressed,   │
                        │  shared across guests, LRU 150 MB)       │
                        └───────────────┬──────────────────────────┘
                                        │ unresolvable?
                                        ▼
                        ┌──────────────────────────────────────────┐
                        │ fallback: device-native TTS  ──▶  silent │
                        │           (AudioSource port)      mode   │
                        └───────────────┬──────────────────────────┘
   ═════════════════════════════════════╪══════════════════════════════════
   PLAY TIME                            ▼
   (client, offline)    ┌──────────────────────────────────────────┐
                        │  Playback Runtime — no network, no model │
                        └──────────────────────────────────────────┘
```

Three time domains, separated on purpose: synthesis happens at plan time,
fetching at prepare time, and **playback touches neither the network nor a
provider**. That separation is what makes §20's offline contract true rather
than aspirational.

### 9.2 Properties

| Concern | Design |
|---|---|
| Invalidation | Key change *is* invalidation. Nothing is mutated in place. |
| Voice version change | `provider_version` participates in the key → new key, old entries age out. |
| Duplicate elimination | Identical text+voice+style = identical key = one file. |
| Disk quota | Soft cap **150 MB**, LRU eviction, never evicting a segment belonging to a `ready` or `playing` run. |
| Cleanup | LRU on write; full sweep on app start if over cap; entries older than 90 days with no hit dropped. |
| Integrity | Store `sha256` of the bytes; verify on read. A corrupt entry is deleted and re-fetched, not played. |
| Offline reuse | Cache is the offline story. A prepared session's segments are all resident before `ready`. |
| Encryption | **Not encrypted.** The content is product-authored guidance, identical for every user, and carries nothing personal. Encrypting it would imply a confidentiality property that does not exist. |
| Sharing across guests | **Yes**, deliberately — see above. |
| Deletion | Guest data deletion does **not** clear the audio cache, because the cache contains no guest data. Documented explicitly so it is a decision, not an oversight. |

### 9.3 Durations feed back

Every cache entry stores the **measured** `duration_ms`. The planner reads
measured durations when available and estimates only when not, so planning
accuracy improves as the corpus warms and §6.4's elastic absorption has less to
do.

### 9.4 Fallback chain

```text
cached asset (hash verified)
    └─ miss/corrupt → fetch pre-generated asset (if configured & online)
        └─ unavailable → device-native TTS
            └─ unavailable → text-only segment: display transcript,
                             hold for min_ms, emit RENDER_DEGRADED
                └─ (never) silent failure
```

The text-only rung matters: a user who is deaf, or whose TTS engine is broken,
still gets a usable session, and §13's transcript requirement makes it cheap.

---

## 10. Privacy and compliance boundary

### 10.1 Data flows per strategy

**Device-native TTS (the shipped default):**

```text
device ──▶ backend        : session create (guest id, check-in id)   [existing]
device ──▶ backend        : session events (segment ids, timings)    [NEW]
device ──▶ OS TTS engine  : product-authored guidance text           [NEW]
device ──▶ (no vendor)
device     local cache    : none (TTS is synthesised per play)
```

**Server pre-generated (the designed upgrade):**

```text
device ──▶ backend        : render manifest request (render_keys only)  [NEW]
backend ──▶ vendor        : product-authored text + voice params        [NEW, build-time]
backend     object store  : audio keyed by render_key                    [NEW]
device ◀── backend/CDN    : audio bytes + hash                           [NEW]
device     local cache    : audio, content-addressed                     [NEW]
```

### 10.2 Classification

| Flow | Data | Purpose | Retention | Guest identity? | Third party? |
|---|---|---|---|---|---|
| session events → backend | segment ids, monotonic offsets, state transitions | resume, completion accounting, outcome | until user deletion, by cascade | **yes** — it is their session | no |
| guidance text → OS TTS | product-authored sentences | speech synthesis | OS-controlled | **no** | OS vendor, outside our control — **disclosed** |
| render request → vendor | product-authored text, voice params | one-off synthesis | vendor's own policy | **no** | yes — requires §10.4 review |
| audio → device cache | product-authored audio | offline playback | 90 days / LRU | **no** | no |

### 10.3 Declaration deltas

| Document | Device-native TTS (shipping) | If pre-generated is added |
|---|---|---|
| `PrivacyInfo.xcprivacy` | **no change** — no new Required Reason API; `AVSpeechSynthesizer` is not one; audio cache files are ours, not `NSUserDefaults` | no change |
| Apple App Privacy | **one addition**: session events extend existing `Usage Data / Product Interaction`, already declared and deletable | no change to user-data answers; vendor is a subprocessor, not a collector |
| Google Data Safety | same: `App activity / App interactions`, already declared | same |
| Android permissions | **no new permission.** Foreground-service audio type is a *service declaration*, and `FOREGROUND_SERVICE_MEDIA_PLAYBACK` must be added — see §12 and §23 |
| iOS entitlements | **none.** Background audio is a `UIBackgroundModes` key, not an entitlement |
| Background modes | **`audio` added** — this is the one real declaration delta |
| Third-party SDK inventory | **one entry**: the TTS plugin (audio playback + TTS), no data collection, no network of its own | **one entry**: the voice vendor, with retention |
| Subprocessors | **no change** | **one addition** — and a policy update, since the list is published |

"No change" above is a claim with evidence, not a shrug: each row names why.

### 10.4 Compliance delta review

Introducing any voice vendor or new SDK requires, **in the same slice**: a
`compliance/third-party-sdks.v1.yaml` entry; a `compliance/subprocessors.v1.yaml`
entry; Apple and Google mapping updates; a privacy-policy revision; and a green
`check_compliance_consistency.py`. That script stays authoritative and is
extended (§23) so a new audio fact cannot be declared in one document and
forgotten in the other four.

**No vendor may silently expand collection**: the gate fails on an SDK in
`pubspec.yaml` that is absent from the inventory, which is the mechanism that
makes this enforceable rather than aspirational.

---

## 11. Content safety boundary

The product's non-clinical positioning is already machine-checked for user-facing
knowledge text by `app/domain/practice/language.py`. Program004 extends the same
guard to every guidance segment and transcript.

Prohibited in content: diagnosis, treatment, cure, therapy, clinical claims,
guaranteed outcomes ("this will fix your anxiety"), and sectarian terminology in
default-visible strings.

Two additions beyond Program003's guard:

1. **Outcome-guarantee patterns** — "will cure", "guaranteed to", "eliminates
   your", "proven to treat". The existing guard catches vocabulary; these are
   constructions.
2. **Generated content must pass before freezing** (§7.2), so the lint runs at
   content-approval time, not only at load time.

This is a content architecture requirement. Program004 builds no clinical engine
and makes no assessment of any user.

---

## 12. Background playback

### 12.1 Required for MVP

Audio that stops when the screen locks is not a meditation app. This is the
minimum viable capability, not an enhancement.

**iOS**

| Capability | MVP | Why |
|---|---|---|
| `UIBackgroundModes: audio` | **yes** | the core requirement |
| `AVAudioSession` category `.playback` | **yes** | continue when locked; respect silent switch = **no**, meditation audio should play |
| Interruption notifications | **yes** | the `interrupted` state depends on them |
| Route-change notifications | **yes** | §5.3 Bluetooth handling |
| Now Playing metadata | **yes** | lock-screen title; cheap and expected |
| Remote commands: play/pause | **yes** | users will press it |
| Remote commands: seek/skip | **no** | §6.5 — there is nothing to seek to |

**Android**

| Capability | MVP | Why |
|---|---|---|
| Audio focus (`AudioManager`) | **yes** | the `interrupted` state |
| `MediaSession` | **yes** | lock-screen and system controls |
| Foreground service, `mediaPlayback` type | **yes** | required to keep playing in background |
| `FOREGROUND_SERVICE_MEDIA_PLAYBACK` permission | **yes** | mandatory on API 34+; this is a real permission delta |
| `POST_NOTIFICATIONS` | **no** | the foreground-service notification does not require it for this type; asking would contradict Program003's declaration |
| Media button / headset hooks | **deferred** | |
| Android Auto / Wear | **no** | §26 non-goal |

### 12.2 Deferred, explicitly

Sleep timer, cross-fade between segments, chapter navigation, playback speed,
downloads for a catalogue, CarPlay/Auto. None is needed to complete a session.

---

## 13. Accessibility

Program003 established an automated floor. Program004 must not regress it and
adds surfaces that need their own treatment.

| Requirement | Design |
|---|---|
| Player control labels | Every control has a semantic label describing the action, not the icon: "Pause the session", not "pause button". |
| Dynamic Type | Player must lay out at 2× text scale. Program003 caught the welcome screen overflowing at exactly this; the player has more text and is more at risk. |
| Non-colour status | Playing / paused / interrupted each have a text or icon signal, never colour alone. |
| Accessible progress | Progress exposed as "4 minutes 20 seconds remaining of 10 minutes", not a bare percentage. |
| Target sizes | 48dp / 44pt minimum, asserted. |
| Haptic cue option | Bell segments may emit a haptic for users who cannot hear them. Opt-in, off by default. |
| Reduced motion | Progress animation respects the OS flag; the timeline still advances. |
| **Users who cannot or do not want audio** | A full **silent mode**: the session runs on the same timeline with transcripts displayed per segment and optional haptics at bells. Not a degraded fallback — a first-class way to use the product. |
| Transcript | **Every speech segment carries a textual representation.** No exceptions: the text is the source the audio is rendered *from*, so a segment without a transcript is a segment we could not have spoken. |

Silent mode also resolves the §9.4 bottom rung and the §20 offline worst case
with the same mechanism, which is why it is worth building properly rather than
as an error path.

---

## 14. Test isolation — mandatory engineering debt

### 14.1 The defect

`backend/tests/conftest.py` runs `alembic downgrade base` then `upgrade head`
against a session-scoped database, and downgrades again at teardown. Two
concurrent runs against one database destroy each other's schema.

This has now cost time in **three** consecutive programs: it produced 12 spurious
failures in Program002, and 4 failures plus 9 errors in Program003. It is not a
flake; it is a design defect with a known cause. Program004 fixes it **before**
adding the integration tests this program requires, because those tests will be
slower and the collision cost higher.

### 14.2 Options

| Option | Isolation | Speed | Cleanup | CI fit | Verdict |
|---|---|---|---|---|---|
| Per-run **schema** | full within one DB | fast — one `CREATE SCHEMA` | `DROP SCHEMA CASCADE` | one service container | **selected** |
| Per-worker schema | full across xdist workers | fast | same | same | subsumed — the key includes worker id |
| Ephemeral database | full | slower — template copy | `DROP DATABASE` | needs create privilege | fallback |
| Ephemeral container | total | slowest, seconds per run | container lifecycle | heavy | rejected for unit/integration |

### 14.3 Selected model: unique schema per test invocation and worker

```text
schema name = test_<run_id>_<worker_id>
  run_id    = 8 hex chars, per pytest session
  worker_id = "main" or the xdist worker ("gw0", "gw1", …)

session start : CREATE SCHEMA test_ab12cd34_gw0
                SET search_path TO test_ab12cd34_gw0
                alembic upgrade head      (inside the schema)
session end   : DROP SCHEMA test_ab12cd34_gw0 CASCADE
```

Requirements and how each is met:

| Requirement | Mechanism |
|---|---|
| Parallel local runs never collide | run id is per-invocation |
| Hosted CI jobs never collide | each job has its own service container *and* its own run id |
| Cleanup is reliable | `DROP ... CASCADE` in a fixture finaliser, plus a startup sweep of `test_%` schemas older than 24h so a killed run cannot accumulate debris |
| A failed run cannot poison the next | the next run's schema name differs; nothing is shared |
| Benchmarks stay isolated | benchmarks keep their own `adaptive_bench` database — already introduced in Program003 |
| **Production cannot select a test schema** | `Settings` rejects a `DATABASE_URL` whose `search_path`/options name a `test_` schema when `app_env == production`; asserted by a test |

The last row is the one that would otherwise be an accident waiting to happen.

### 14.4 Proof obligation

A test that runs **two full pytest sessions concurrently** against one PostgreSQL
instance and asserts both pass. Without that, the fix is a claim.

---

## 15. Data model

### 15.1 New entities — and what is deliberately not created

| Entity | Created? | Reasoning |
|---|---|---|
| `session_definitions` | **yes** | Historical reproducibility (§4C) is impossible without a frozen, versioned content row. |
| `session_events` | **yes**, append-only | "Where did they stop" cannot be derived from a status column. Append-only because an event log that can be rewritten is not evidence. |
| `audio_renders` | **yes** | Content-addressed dedup, measured durations, integrity hashes. |
| `audio_assets` | **no** | The render *is* the asset. A second table would add a join and a lifecycle for nothing — the key already identifies the bytes. |
| `meditation_session_plan` | **no** | The plan stays JSONB on `sessions` plus a `plan_hash` column. It is written once, read whole, never queried by field. Normalising it would buy nothing and cost a join on the hot path. |
| `meditation_session_run` | **no** | A session has exactly one run. A separate table implies multiple runs per session, which the product does not have. If resumable multi-run sessions ever ship, this is the seam to split. |

Two tables' worth of restraint here is deliberate: Program001's SDD instruction
to take the simpler design absent a query requirement still applies.

### 15.2 Relationships

```text
guest_profiles ──┬──▶ check_ins ──▶ sessions ──┬──▶ session_feedback
                 │                     │        │
                 │                     │        ├──▶ recommendation_candidates
                 │                     │        │
                 │                     │        └──▶ session_events      [NEW]
                 │                     │                (append-only)
                 ├──▶ experiment_assignments    │
                 └──▶ experiment_exposures ◀────┘ exposure raised on first
                                                  playing transition (§16)
                                       │
                 session_definitions ◀─┘ [NEW]  frozen content version
                       │
                       └──▶ audio_renders [NEW]  content-addressed, guest-free
```

**Guest-linked (must cascade on delete, must appear in export):**
`session_events`.

**Not guest-linked (must NOT cascade, must NOT appear in export):**
`session_definitions` (product content), `audio_renders` (product audio). Deleting
a guest must not delete the product's own content — an obvious statement that is
exactly the kind of thing a cascade gets wrong.

### 15.3 `session_events`

Append-only: no update, no delete except by guest-deletion cascade. Enforced by a
repository that exposes only `append` and `read`, and asserted by a test.

```text
id · session_id(FK, cascade) · sequence(int) · event_type · segment_index
occurred_at(wall, audit) · elapsed_ms(monotonic) · command_id(nullable)
detail(JSONB, bounded)
UNIQUE(session_id, sequence)
```

`elapsed_ms` is the monotonic playback position; `occurred_at` is wall clock and
is for audit only. Both are stored because they answer different questions, and
conflating them is how "the session lasted 3 hours" bugs happen.

---

## 16. Experiment exposure semantics

Program003 separated assignment from exposure. Program004 must not collapse
future audio experiments into one rule, because different experiment classes
become "seen" at genuinely different moments.

| Experiment class | Exposure trigger | Why |
|---|---|---|
| Presentation copy (existing) | explanation rendered on screen | already shipped; unchanged |
| Session structure (silence lengths, segment order) | first transition to `playing` | the structure is experienced from the first sample |
| Voice / renderer choice | first **speech** segment begins playing | a bell says nothing about the voice |
| Segment-scoped content variant | the **specific variant segment** begins playing | a user who abandons at 00:30 never heard the 07:00 variant, and counting them dilutes the result to nothing |

Encoded as an `ExposureTrigger` on the experiment definition —
`ON_RENDER | ON_PLAYBACK_START | ON_FIRST_SPEECH | ON_SEGMENT_START(segment_id)` —
so the rule is data on the experiment, not a branch in the runtime.

The existing idempotency holds: one exposure per `(guest, experiment, context)`,
with `context` being the session id for session-scoped experiments and
`session_id:segment_id` for segment-scoped ones.

---

## 17. Observability

### 17.1 Events

`session_created` · `session_prepared` · `session_started` · `segment_started` ·
`segment_completed` · `playback_paused` · `playback_resumed` ·
`playback_interrupted` · `playback_focus_regained` · `route_changed` ·
`session_completed` · `session_abandoned` · `render_cache_hit` ·
`render_cache_miss` · `render_failure` · `timeline_compressed` ·
`timeline_drift_exceeded` · `silent_mode_used`

### 17.2 Never logged

Spoken text or transcripts. Generated content. Any credential or token. Guest
export contents. Free-text feedback notes. The guest UUID. Program003 already
asserts the last two with a test that drives the whole slice with logging
captured; Program004 extends that test to cover the playback and render paths.

Diagnostic identity is a per-run `run_ref` (random, not derived from the guest),
so a support conversation can reference a session without naming a person.

### 17.3 Metrics

| Metric | Definition |
|---|---|
| time-to-first-audio | `start` command → first sample rendered |
| start success rate | `ready → playing` without failure |
| completion rate | `completed / started`, segmented by practice and duration |
| render failure rate | failures / render attempts, by failure class |
| cache hit rate | hits / lookups |
| interruption recovery rate | `interrupted → playing` / `interrupted` |
| playback crash-free rate | sessions without `runtime_error` |
| silent-mode share | accessibility signal, not a vanity metric |

---

## 18. Performance budgets

Measured on the workstation baseline unless stated; **never reported as OCI
figures**. Guest and anonymous paths benchmarked separately, as Program003's
regression work showed they diverge.

| Budget | Target |
|---|---|
| Player screen ready (plan present) | p95 < 300 ms |
| Time-to-first-audio, warm cache | p95 < 800 ms |
| Time-to-first-audio, device TTS cold | p95 < 2,000 ms |
| Pause → silence | p95 < 100 ms |
| Resume → audio | p95 < 250 ms |
| Session-plan generation added to `POST /v1/sessions` | p95 < 50 ms |
| `POST /v1/sessions` total | p95 < 250 ms |
| Event batch ingest | p95 < 120 ms |
| DB queries per session create | ≤ 6 |
| DB queries per event batch | ≤ 2 |
| Client audio memory | < 40 MB resident |
| Backend container RSS | < 250 MiB (Program003 flag, unchanged) |

**Explicit anti-regression rule.** Program003's guest recommendation path is
+116% over Program002 for a defensible reason. That is a one-off justified cost,
**not a precedent**. Program004 measures against the Program003 numbers as the
new baseline and must justify any >25% increase on its own evidence. Accumulated
"each step was only a bit slower" is how a product becomes unusable without any
single commit being at fault.

---

## 19. Cost architecture

Covered quantitatively in §8.3. The structural commitments:

- generation is **build-time and one-off**, because the corpus is bounded;
- repeated playback of popular content has **zero** marginal generation cost;
- the cache key is content-derived, so popularity *increases* the hit rate rather
  than the bill;
- device-native TTS has no monetary cost at all, and is what ships first;
- storage and egress are the only recurring components, on the order of tens of
  megabytes total.

If a future catalogue of long-form recordings is ever introduced, this analysis
must be redone — it depends entirely on the corpus being small.

---

## 20. Offline contract

| Question | Answer |
|---|---|
| Can a prepared session run fully offline? | **Yes.** `ready` means every segment is resolvable locally. This is the definition of `ready`, not a side effect. |
| Can a new session be started offline? | **Yes** with device-native TTS, provided the plan is available. A plan requires the API, so a never-online install cannot start one; a previously-online one can. |
| Partially cached audio? | `preparing` resolves each segment independently. Missing segments fall back per §9.4. The session starts; it does not wait for perfection. |
| Does native TTS provide a fallback? | Yes — the third rung of the chain, and the reason the chain rarely reaches the fourth. |
| Are online-only voices clear to the user? | Yes. A voice requiring a fetch is labelled in the picker and cannot be selected for a session that cannot prepare it. |
| Does losing network mid-session end it? | **No.** A `playing` session makes no network call. Event journal writes buffer locally and flush later. |

Degradation is graceful by construction: the failure mode is a plainer voice, not
a dead session.

---

## 21. Failure taxonomy

| Code | Meaning | Retryable | Recoverable | User-actionable | Fatal to session |
|---|---|---|---|---|---|
| `CONTENT_PLAN_INVALID` | plan fails schema/invariant validation | no | no | no | **yes** |
| `AUDIO_ASSET_MISSING` | keyed asset absent everywhere | yes | yes (fallback) | no | no |
| `RENDER_UNAVAILABLE` | no renderer can produce a segment | yes | yes (silent mode) | no | no |
| `PROVIDER_TIMEOUT` | renderer exceeded deadline | **yes**, backoff | yes | no | no |
| `PROVIDER_REJECTED` | renderer refused input | no | yes (fallback) | no | no |
| `CACHE_CORRUPTION` | hash mismatch on read | yes (after delete) | yes | no | no |
| `UNSUPPORTED_CODEC` | device cannot decode | no | yes (re-fetch alt / TTS) | no | no |
| `AUDIO_FOCUS_DENIED` | focus not granted at start | yes | yes | **yes** — "another app is using audio" | no |
| `PLAYBACK_RUNTIME_ERROR` | unexpected runtime fault | no | via `recover()` | no | **yes** for the attempt |
| `STORAGE_EXHAUSTED` | cannot write cache | no | yes (stream/TTS) | **yes** — "free up space" | no |
| `NETWORK_UNAVAILABLE` | no connectivity during prepare | yes | yes (TTS) | no | no |

The pattern: **almost nothing is fatal.** The only two fatal classes are an
invalid plan (a bug on our side) and a runtime fault. Everything a user is likely
to actually encounter — no signal, full disk, another app playing — degrades.

---

## 22. Security requirements

Program004 must not weaken Program003.

| Requirement | How |
|---|---|
| No cloud secret in the Flutter bundle | the client never talks to a voice vendor; it talks to our backend, which holds any credential. Enforced by the existing credential scanner, extended to audio config files. |
| No provider master key in the client | same boundary |
| No credential logged | §17.2, plus the existing logging test |
| Guest identity not used as provider metadata | §8.5, unit-tested on the serialised request |
| No public writable audio bucket | assets are read-only to clients; writes originate from the backend only |
| Remote asset integrity | every asset carries `sha256`; verified before playback; a mismatch deletes and re-fetches rather than plays |
| Transport | HTTPS only, unchanged from Program003; no new cleartext exception |

If cloud synthesis is later introduced, the client's request goes to our backend,
which calls the vendor. The client never holds a vendor credential. This is
non-negotiable and is why §8.4 rejects real-time cloud synthesis on the playback
path regardless of quality.

---

## 23. Store-compliance consequences

Summarised in §10.3. The concrete deltas for the shipping design:

| Artefact | Delta |
|---|---|
| `PrivacyInfo.xcprivacy` | **no change** — no new Required Reason API |
| `compliance/apple/app-privacy.v1.yaml` | session events fold into existing `Usage Data / Product Interaction`; **no new category** |
| `compliance/google/data-safety.v1.yaml` | same, under `App activity / App interactions` |
| Android permissions | **`FOREGROUND_SERVICE_MEDIA_PLAYBACK` added** — the only new permission, and `check_android_store_readiness.py`'s allowlist must be extended with its reason |
| iOS entitlements | none |
| Background modes | **`audio` added** to `UIBackgroundModes` |
| `compliance/third-party-sdks.v1.yaml` | one entry for the audio/TTS plugin: native code yes, data collection none, network none |
| `compliance/subprocessors.v1.yaml` | no change for the shipping design |
| `compliance/retention.v1.yaml` | `session_events` retention added; audio cache retention documented as device-local, 90 days |
| Privacy policy | discloses session events, and the OS-TTS caveat from §8.4 |

`check_compliance_consistency.py` is extended to cover the audio facts: a
declared foreground-service permission must have a recorded reason, and a new
SDK entry must exist for any plugin with native code. The script stays the single
authority — four documents that can disagree are four chances to file a false
declaration.

---

## 24. Brand blocker treatment

```text
STORE_IDENTITY_GATE     = EXTERNAL_BLOCKED    (brand, bundle ids, domain, email)
PROGRAM004_ENGINEERING_GATE = independent
```

Program004 is not blocked on the brand. Nothing in this design requires a final
bundle identifier, and the working identifiers are untouched — replacing them
later remains a configuration change, exactly as Program003 left it.

Specifically: audio assets are keyed by content hash, not by bundle id or
domain; no CDN hostname is baked into the client; no store record is created.

---

## 25. Implementation slices

One Program004 implementation task, six coherent slices. **No further planning
chain**: this SDD is the contract, and the next task builds against it.

| Slice | Content | Proves |
|---|---|---|
| **A — Infrastructure hygiene** | per-run schema isolation; deterministic fixtures; concurrency proof | two full suites run concurrently and both pass |
| **B — Session domain** | typed segment model; `SessionPlan` v2 + `plan_hash`; `session_definitions`; state machine; `session_events`; migration | determinism, reproducibility, transition legality |
| **C — Playback core** | timeline execution; speech/silence/bell; pause/resume; interruption; process recovery; monotonic clock; elastic silence | a session survives a phone call and an app kill |
| **D — Audio provider layer** | `SpeechRenderer` port; device-native adapter; content-addressed cache; fallback chain; silent mode | provider substitution without touching domain code |
| **E — Product integration** | recommendation → session wiring; player UI; accessibility; transcripts; history and outcome | a person can complete a meditation |
| **F — Compliance and evidence** | manifests; privacy mappings; permission allowlist; performance; memory; Android and iOS release builds | the gates stay green and the declarations stay true |

Slice A is first because every later slice adds integration tests, and adding
them to a suite that cannot run concurrently multiplies the existing cost.

---

## 26. Non-goals

Not in Program004: social features, community, subscriptions or payment, live
instructor streaming, medical recommendations, account registration, user-generated
public content, unrestricted live LLM narration, multi-device sync, smartwatch
support, a downloadable catalogue of long recordings, or any vendor-specific
architecture.

Each is excluded because none is required to find out whether a person will
complete a meditation session twice in a week, which is the only question this
program exists to answer.

---

## 27. Interruption and recovery flow

```text
        playing
           │
   ┌───────┴────────┐
   │ focus lost     │  (call · other app · route loss · Bluetooth away)
   ▼                │
interrupted         │
   │ journal: playback_interrupted(segment, elapsed_ms)
   │ audio stopped, monotonic accumulator frozen
   │
   ├── focus regained ──▶ paused ──user──▶ playing (resume at boundary)
   │
   └── user ends / expiry ──▶ abandoned (completion_ratio recorded)


        process death
           │
           ▼
   relaunch ──▶ read journal ──▶ last confirmed boundary?
                                    │
              ┌─────────────────────┴──────────────────────┐
              │ boundary is a segment start                │ mid-speech
              ▼                                            ▼
     offer resume at that segment              offer resume at the START
                                                of that speech segment
                                    │
                            user declines ──▶ abandoned
```

Resume never lands mid-utterance. The cost is repeating up to one sentence; the
alternative is joining a sentence halfway through, which is worse than either
repeating it or skipping it.

---

## 28. Architecture decisions

### ADR-004-01 — Session plan vs monolithic audio

**Alternatives:** one rendered MP3 per session; one TTS string per session; typed
segment timeline.
**Selected:** typed segment timeline.
**Rationale:** a monolith cannot express silence the runtime can shorten, cannot
be partially cached, cannot be partially localised, and cannot record which
*part* a user abandoned in. A single TTS string makes silence into spoken pauses
and destroys timing control. The segment model also makes segment-scoped
experiments (§16) expressible at all.
**Consequences:** the planner gets more complex; the renderer gets simpler; the
cache becomes effective because segments repeat across sessions where whole
sessions do not.

### ADR-004-02 — Provider-neutral voice architecture

**Alternatives:** code directly against one TTS SDK; thin wrapper; full port with
capability negotiation.
**Selected:** full port (`SpeechRenderer`) with declared capabilities.
**Rationale:** the first provider is chosen under today's constraints (no
credentials, no brand), and those constraints will lift. Capability negotiation
is needed because the adapters differ in kind — one is deterministic and offline,
another is higher quality and needs a fetch.
**Consequences:** one indirection; provider substitution becomes a test rather
than a migration; no domain code imports a vendor.

### ADR-004-03 — First audio rendering strategy

**Alternatives:** device-native TTS; packaged prerecorded; server pre-generated;
real-time cloud.
**Selected:** device-native TTS first, server pre-generated designed as the
immediate second adapter, real-time cloud rejected outright.
**Rationale:** §8.2–8.4. Device-native is the only option with no external
credential dependency, which is decisive given that the Apple account, the Google
account, the brand and any vendor account are all unresolved. Real-time cloud
fails on latency, offline, cost and privacy simultaneously.
**Consequences:** MVP voice quality is merely acceptable; §6.4's elastic silence
is mandatory rather than optional; the Android OS-TTS network caveat must be
disclosed; the upgrade path is an adapter swap, not a redesign.

### ADR-004-04 — Caching strategy

**Alternatives:** no cache; guest-keyed cache; content-addressed cache.
**Selected:** content-addressed, keyed on render inputs, shared across guests on
a device.
**Rationale:** the corpus is tiny and highly repeated, so a content key gives a
near-perfect hit rate; a guest-keyed cache would store N identical copies and
manufacture a guest-linked data category that need not exist.
**Consequences:** guest deletion does not clear the cache (documented, §9.2);
integrity must be verified on read; disk is bounded by LRU.

### ADR-004-05 — Playback persistence and recovery

**Alternatives:** status column only; periodic position snapshots; append-only
event journal.
**Selected:** append-only journal, with resume at confirmed segment boundaries.
**Rationale:** a status column cannot answer where a user stopped, which is the
question the outcome layer most needs. Periodic snapshots lose the ordering that
makes interruption analysis possible. Append-only makes the log evidence rather
than state.
**Consequences:** one more table and a bounded write path; events batch to avoid
per-segment round trips; the journal is guest-linked and must cascade and export.

### ADR-004-06 — Database test isolation

**Alternatives:** per-run schema; per-worker schema; ephemeral database;
ephemeral container.
**Selected:** unique schema per invocation **and** worker.
**Rationale:** §14.2. Full isolation at the cost of one DDL statement, with no
extra infrastructure and no privilege beyond schema creation.
**Consequences:** `search_path` must be set per connection; migrations run inside
the schema; a production guard is required so a test schema can never be selected
in production; a stale-schema sweep handles killed runs.

### ADR-004-07 — Experiment exposure semantics

**Alternatives:** one global rule; per-experiment trigger.
**Selected:** per-experiment `ExposureTrigger`.
**Rationale:** a voice experiment and a copy experiment become "seen" at
genuinely different moments, and a single rule would either over-count
(everyone assigned) or under-count (only completers).
**Consequences:** the trigger is data on the experiment definition; the runtime
evaluates triggers without knowing what any experiment means.

### ADR-004-08 — Background playback scope

**Alternatives:** foreground only; full media-app treatment; audio + minimal
controls.
**Selected:** background audio with play/pause and lock-screen metadata; no seek,
no skip, no sleep timer in MVP.
**Rationale:** audio that stops on screen lock makes the product unusable, so
background audio is not optional. Everything beyond play/pause is either
meaningless here (seek, §6.5) or deferrable.
**Consequences:** one new Android permission and one iOS background mode, both
declared and justified; a foreground service on Android; §23 compliance deltas.

### ADR-004-09 — Offline degradation

**Alternatives:** online-required; online-preferred with hard failure;
graceful degradation.
**Selected:** graceful degradation, with `ready` defined as "fully resolvable
locally".
**Rationale:** people meditate on planes, in basements and on the underground.
A session that dies when a train enters a tunnel is a broken product.
**Consequences:** `preparing` must resolve every segment before `ready`; the
fallback chain must be complete including silent mode; event writes buffer.

### ADR-004-10 — Adaptive and generative boundary

**Alternatives:** allow live generation; allow generation with runtime filtering;
require validation and freezing before planning.
**Selected:** validate and freeze before the planner can see it; the playback
runtime has no model access at all.
**Rationale:** runtime filtering still puts a model on the critical path of a
user's experience, with its latency, its failure modes and its capacity to say
something harmful during a vulnerable moment. Freezing makes generated content
auditable and reproducible, which live generation can never be.
**Consequences:** generated content cannot be personalised per session in real
time — accepted deliberately; an approval gate is needed before generated content
ships; the runtime's model-free property is testable.

---

## 29. Implementation Definition of Done

The later builder must not invent acceptance criteria. Every item below requires
executed evidence.

**Infrastructure**
- [ ] two full backend test suites run **concurrently** against one PostgreSQL instance; both pass
- [ ] a killed run leaves no schema that affects the next run
- [ ] production configuration cannot select a `test_` schema (asserted)

**Session domain**
- [ ] identical intent + definition version ⇒ identical `plan_hash`
- [ ] every legal transition exercised; every illegal transition rejected
- [ ] `session_events` is append-only (update and delete unavailable)
- [ ] a session remains interpretable after its content definition is superseded
- [ ] migration `upgrade → downgrade → upgrade` on PostgreSQL 16, no pending diff

**Playback**
- [ ] speech, silence and bell segments play in order with correct durations
- [ ] pause and resume preserve position; elapsed uses a monotonic source
- [ ] simulated focus loss produces `interrupted`; focus return produces `paused`, never auto-play
- [ ] process kill and relaunch resumes at a segment boundary, never mid-speech
- [ ] duplicate `complete` is idempotent; out-of-order commands are dropped
- [ ] elastic silence absorbs speech overrun; total duration invariant holds

**Audio**
- [ ] one production-quality provider integrated end to end
- [ ] **provider substitution test**: a second (fake) renderer runs a full session with no domain code change
- [ ] cache hit avoids re-render; hit rate asserted over a repeated session
- [ ] corrupt cache entry is detected, deleted and recovered from
- [ ] full fallback chain exercised, including silent mode
- [ ] `RenderRequest` contains no guest identifier, session id or experiment arm

**Offline**
- [ ] a prepared session completes with networking disabled
- [ ] network loss mid-session does not end the session

**Privacy, security, compliance**
- [ ] no secret in the client bundle (credential scan, extended to audio config)
- [ ] `session_events` covered by guest **delete** and **export**
- [ ] `session_definitions` and `audio_renders` are **not** deleted by guest deletion
- [ ] `check_compliance_consistency.py` green with the new audio facts
- [ ] privacy manifest unchanged, with evidence that it should be
- [ ] new Android permission present in the allowlist with a recorded reason
- [ ] no spoken text, transcript, note or guest id in logs

**Accessibility**
- [ ] automated floor: tap targets, contrast, labels, 2× Dynamic Type on the player
- [ ] every speech segment has a transcript
- [ ] silent mode completes a full session
- [ ] **manual checklist** recorded separately as manual: screen-reader traversal on device, focus behaviour on segment change, reduced motion, haptic bells, audio-route handling with real Bluetooth hardware

**Builds and regression**
- [ ] backend suite, Flutter analyze and test, ruff, mypy strict, credential scan
- [ ] Android release AAB builds; merged-manifest permission audit passes
- [ ] iOS `--no-codesign` release build on CI; privacy manifest embedded
- [ ] ARM64 container builds and serves with no database and no AI key
- [ ] performance benchmarks against the §18 budgets, guest and anonymous separately
- [ ] memory benchmark against the 250 MiB flag
- [ ] cost estimate if any paid synthesis is introduced

**Explicitly not claimable by automated test:** human voice quality, whether the
session *feels* like a meditation, and prosody. These require listening, and the
manual checklist says so rather than pretending a test covers them.

---

## 30. Quality gate

| # | Question | Answer |
|---|---|---|
| 1 | Replace the voice provider without touching meditation domain code? | Yes — ADR-004-02; substitution is a DoD test |
| 2 | Same session on prerecorded audio tomorrow? | Yes — same segment model, different adapter and `render_key` |
| 3 | Session continues if network disappears after preparation? | Yes — `ready` means locally resolvable; §20 |
| 4 | Phone call without corrupting completion state? | Yes — `interrupted` is a distinct state; §5.3, §27 |
| 5 | Distinguish pause from abandon? | Yes — separate states, separate events, `completion_ratio` |
| 6 | Historical sessions reproducible after content updates? | Yes — frozen `session_definitions` + `plan_hash`; §4C |
| 7 | Experiments distinguish assignment from exposure? | Yes — preserved, and refined per class; §16 |
| 8 | Two full backend test runs concurrently? | Yes — ADR-004-06, with a concurrency proof in the DoD |
| 9 | Privacy declarations derived from actual data flows? | Yes — §10.1 flows map to §23 deltas; consistency enforced in CI |
| 10 | Repeated popular content avoids repeated generation cost? | Yes — content-addressed cache; §8.3, §9 |
| 11 | Player functions without an LLM? | Yes — no model on any playback path, by construction and by test |
| 12 | Future generative content without giving the LLM playback control? | Yes — validate, freeze, then plan; ADR-004-10 |
| 13 | New guest-linked data deleted and exported correctly? | Yes — `session_events` cascades and exports; non-guest tables deliberately do not |
| 14 | Operates without shipping privileged vendor credentials? | Yes — client never calls a vendor; §22 |
| 15 | **Produces a product someone can actually meditate with?** | Yes — bell, voice, real silence, lock-screen playback, survives a phone call, resumes after a crash, works offline, and has a silent mode for people who cannot use audio |

No "no" remains.

---

## 31. Disposition

```text
PROGRAM004_SDD_ACCEPTABLE_FOR_IMPLEMENTATION
```

Carried forward as recorded constraints, not blockers:

- Program003 is `PROGRAM003_IMPLEMENTED_CI_GREEN_PENDING_REMOTE_CLOSURE`;
  Program004 implementation must not merge before PR #3.
- `STORE_IDENTITY_GATE = EXTERNAL_BLOCKED` — independent of this program.
- Apple and Google credentials, signing, brand and DNS remain external.

## 32. Product invariants carried forward

1. wellness, not medical diagnosis or treatment;
2. source-grounded internally, non-sectarian in user-facing language;
3. deterministic core, independent of any external AI;
4. guest-first usability;
5. OCI A1 resource discipline;
6. store-sensitive capabilities deferred or isolated;
7. individual-first commercialization with future company migration;
8. no false test or deployment claims.
