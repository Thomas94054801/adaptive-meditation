# Program004 — Core Adaptive Meditation Session Engine, Audio Runtime, Voice Delivery and Test Isolation

Accepted SDD: `44c4419365b9701ad2a9813159ca4a85dae18bc3`
(`docs/sdd/PROGRAM004-core-adaptive-meditation-experience.md`)

Branch: `program004/core-adaptive-meditation-sdd`, based on
`a75b6ca1ccde1d2592dc588e9597ee93d0fadd7d` (Program003 head, PR #3).

## What shipped

| Slice | Commit | Subject |
|-------|--------|---------|
| A | `6768dd9` | isolate concurrent PostgreSQL test runs |
| B | `fe66685` | immutable session definitions and typed timeline |
| C | `480c283` | playback runtime; two budget violations closed |
| D | `ce1469f` | provider-neutral audio with traceable assets |
| E | `62012c9` | audio playback, background mode, transcript |
| F | this commit | evidence, budgets, CI, compliance |

## The three SDD corrections, and where each landed

**1. Elastic silence cannot always preserve the target duration.**
`app/domain/timeline/timing.py` does the arithmetic explicitly and records it:
`speech_overrun_ms`, `available_shrinkable_ms`, `absorbed_ms`, `extended_by_ms`
and a per-silence allocation. The priority order is never negative silence,
never truncate guidance, never breach a floor, then extend the session and say
so. `SilenceAllocation` refuses to hold a value below its floor, so the failure
the review warned about is unrepresentable rather than merely untested. All four
outcomes are pinned, including the exactly-at-budget boundary where every
elastic millisecond is spent and none is borrowed.

**2. Native TTS is not automatically offline.**
`app/domain/audio/capability.py` classifies a voice from probe evidence only:
`LOCAL_CONFIRMED` requires a render that succeeded with the network down.
`LOCAL_UNCONFIRMED` is the honest label for a voice only ever seen working
online, and it is the label the shipped configuration carries. `may_claim_offline`
returns true for exactly one of the four, and a test pins that set. The privacy
policy states the Android OS-level behaviour in plain words rather than glossing
it, and no offline claim appears anywhere in the product.

**3. Localisation is not translation.**
`LocaleSupport` holds two independent contracts — `content_approved` and
`voices` — and `supported` requires both. `reason_unsupported()` distinguishes
"a voice can speak it, but no approved content exists" from "approved content
exists, but no voice can speak it", because they are different problems.

## Defects found and fixed during the program

These were found by building, not by reviewing.

1. **`alembic_version` double-qualification** (Slice A). Passing both a
   `search_path` and `version_table_schema` made reflection and comparison
   disagree, so `alembic check` reported a phantom `remove_table`. Fixed by
   dropping `version_table_schema` in online mode.

2. **Silence floors were far too low** (Slice B). The first planner produced a
   `minimum_total_ms` of 84 s for a 604 s session — not a shorter meditation but
   a different thing entirely. The floor is now proportional to the silence
   actually allocated; a ten-minute session cannot compress below 45% of target.

3. **A route shadowed an existing one** (Slice B). Adding
   `GET /v1/sessions/{session_id}` silently swallowed `/v1/sessions/history`,
   because FastAPI matches in registration order. It broke eleven history and
   privacy tests. Router order is now explicit, commented, and pinned by
   `test_literal_session_paths_are_not_shadowed`.

4. **Event ingest was 400 round trips for a 200-event batch** (Slice C), against
   an SDD budget of two. A select and an insert per event became one sequence
   probe and one bulk insert, with in-batch duplicates removed first — without
   that, the unique constraint rejects the whole insert rather than the
   duplicate.

5. **Command replay was detected on sequence alone** (Slice C). SDD 5.4 says a
   replayed `command_id` returns the same result without re-applying; the same
   command retried under a bumped sequence was being applied twice. A test
   covers exactly that case.

6. **A command could be applied while its journal entry was lost** (Slice B).
   Commands and events share one per-session counter, so a command landing on a
   taken sequence found the row already present and continued. It now rolls the
   whole request back: a run nobody can reconstruct is worse than a rejected
   command.

7. **The event type set did not match the SDD** (Slice B). Section 17.1
   enumerates `playback_focus_regained` and `route_changed`; the implementation
   had invented `audio_route_changed` and was recording an interruption ending
   as a second pause, conflating two different facts in the journal. Aligned to
   the SDD verbatim, plus exactly two additions the corrections require
   (`timeline_extended`, `playback_failed`), with a test pinning that difference
   so it cannot grow quietly.

8. **`render_key` did not match SDD 9.1** (Slice D). It lacked NFC
   normalisation, so the same visible sentence authored with decomposed accents
   produced a different key. It would have shown up as an unexplained cache-miss
   rate the first time a non-English locale shipped.

9. **The player read an inherited widget during `initState`** (Slice E), which
   is not allowed and threw on first build. Moved to `didChangeDependencies`.

10. **The permissions test only looked for prohibited permissions** (Slice E),
    so it passed unchanged after background audio was added. It now checks both
    directions: a capability in compliance must appear in both manifests, and a
    permission in a manifest must be accounted for in compliance.

## Test isolation — the mandatory Program003 debt

Closed in Slice A. Each test invocation creates its own PostgreSQL schema
(`test_<epoch>_<run>_<worker>`), migrates into it, and drops it in a `finally`.
Stale schemas older than 24 h are swept on start, so a killed run cannot leak.

The gate: **two full suites run concurrently against the same database, both
exit 0, zero schemas left behind.** Identifiers pass through
`assert_safe_identifier` before reaching any DDL, including the injection case
`test"; DROP SCHEMA public CASCADE; --`. A production configuration that names a
test schema — directly or through a `search_path` in the URL — fails at settings
validation rather than at runtime.

## Evidence

### Backend

```
505 tests, exit 0, PostgreSQL 16.15
ruff check . && ruff format --check .   clean
mypy                                    clean, 69 source files
```

Migrations 0004 and 0005 each verified `upgrade -> downgrade one step ->
upgrade`, with `alembic check` reporting no pending autogenerate diff.

### Flutter

```
107 tests, exit 0
flutter analyze                         clean
```

### Gates

```
credential scan                         clean, 229 files
compliance consistency                  PASS
android store readiness                 PASS
store release gate                      BLOCKED — brand, bundle id, domain only
```

The release gate's blocked items are STORE_IDENTITY_GATE external dependencies.
They are not engineering work and do not block this program.

## Performance

**MEASUREMENT ENVIRONMENT: Apple Silicon (arm64) macOS workstation, Python
3.12.14, local PostgreSQL 16.15. NOT AN OCI A1 MEASUREMENT. No OCI deployment
exists and no OCI credential is configured.**

Produced by `backend/scripts/benchmark_paths.py`, committed this program. The
Program003 figures below were **re-measured on the Program003 commit with the
same script**, because the numbers in `PROGRAM003_STATUS.md` came from an
uncommitted ad-hoc script and comparing against them would compare two
harnesses rather than two commits.

| Path | Program003 p95 | Program004 p95 | Delta | Budget |
|------|----------------|----------------|-------|--------|
| recommendation API (no guest) | 0.825 ms | 0.841 ms | +1.9% | 150 ms |
| recommendation API (with guest) | 1.558 ms | 1.618 ms | +3.9% | 150 ms |
| history API | 1.901 ms | 2.036 ms | +7.1% | 300 ms |

No path exceeds the SDD's 25% relative guard. New Program004 paths, 200 runs
each:

| Path | p50 | p95 | Budget |
|------|-----|-----|--------|
| session create (plan v1 + v2) | 3.798 ms | 4.070 ms | 250 ms |
| prepare (render manifest) | 3.014 ms | 3.170 ms | 250 ms |
| event batch ingest (20 events) | 3.583 ms | 3.806 ms | 120 ms |
| playback state read | 1.598 ms | 1.670 ms | 120 ms |

Query counts are asserted rather than assumed, in `tests/test_playback_runtime.py`:
session creation stays within six queries with definition freezing added, and an
event batch costs one sequence probe and one insert regardless of size — proven
at 200 events.

## Memory

**MEASUREMENT ENVIRONMENT: Colima VM (2 CPU, 4 GB) on the same workstation.
ACTUAL OCI DEPLOYMENT: NOT MEASURED.**

| Quantity | Program003 | Program004 | Threshold |
|----------|-----------|------------|-----------|
| Container RSS, idle | 146.2 MiB | 147.6 MiB | flag above 250 MiB |
| Container RSS, after 150 sessions | — | 158.3 MiB | — |
| Container RSS, after 600 sessions | — | 159.0 MiB | — |

The last two lines are the point: quadrupling the work added 0.7 MiB, so
resident memory tracks the working set rather than the number of sessions
served. Each session writes a plan, a definition reference and about 25 journal
rows, all of which go to the database rather than staying resident.

**Correction to a recorded figure.** `PROGRAM003_STATUS.md` records an image
size of 73.1 MB. Building that exact commit's image on this machine gives
**343 MB**, and Program004's is **345 MB** — a like-for-like delta of +2 MB
(+0.6%). The 73.1 MB figure is not reproducible by `docker images` and was
evidently measured another way; it is left in place in that document rather than
silently rewritten, and flagged here.

## Dependencies

**Program004 added no dependency, in either the backend or the app.** Speech
comes from the platform's own synthesiser and audio focus from the platform's
own session API, both behind first-party ports. The bell tones are generated by
`scripts/generate_bells.py`. A plugin would have been the obvious way to build
this and would have enlarged the reviewed SDK surface for nothing.

## Audio asset provenance

Three bells, generated from arithmetic in `scripts/generate_bells.py`: a small
inharmonic partial series over a fundamental, each partial decaying at its own
rate, with a 15 ms fade at both ends so the file neither starts nor ends on a
step change. Peak levels are 0.51–0.63 of full scale, so nothing clips on a
device that applies its own gain.

`assets/audio/PROVENANCE.json` records origin, licence, generator and sha256 per
file. CI regenerates and compares byte for byte, so a swapped file or an
imported sample fails the build. **No third-party audio was imported**, which is
a licensing decision rather than an aesthetic one: store review is the wrong
place to discover that a "free" sample was not free.

## Capabilities this program actually created

Exactly one new platform capability, declared in three places that a test checks
against each other:

- iOS `UIBackgroundModes: audio` — and nothing else in that array;
- Android `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_MEDIA_PLAYBACK`, both
  listed with reasons in the store-readiness allowlist;
- `compliance/permissions.v1.yaml` `background_audio: requested: true`.

**No microphone permission. No health declaration. No cloud TTS subprocessor.**
None of those facts exists in the code, so none is declared. The Android system
TTS engine may itself synthesise over the network; that is an OS behaviour
outside the app, and it is disclosed in the privacy policy rather than listed as
a subprocessor we engaged.

## Known gaps

1. **No OCI deployment.** Every figure above is from this workstation or a local
   VM. Nothing has been deployed.
2. **`resolve_timing` has no production caller yet.** It is tested, not wired:
   nothing measures real speech duration until an audio engine reports one. The
   arithmetic and its boundaries are proven; the feedback loop is not.
3. **The audio session port has no platform implementation.**
   `SilentAudioSession` grants focus, reports an unknown route and never
   interrupts. The player's behaviour under interruption is fully tested against
   a controllable fake, but no real focus loss has been observed on a device.
4. **No voice-quality claim is made.** No automated test can make one, and none
   is attempted here.
5. **Offline capability is `LOCAL_UNCONFIRMED`.** No probe with the network
   disabled has been run on a real device, so no offline claim is permitted.
6. **Device audio memory is unmeasured.** The SDD's 40 MB client budget needs a
   device; the app plays no audio file yet.
