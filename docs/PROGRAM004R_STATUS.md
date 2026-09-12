# Program004R — Real Audio and Durable Playback

Amended SDD: `docs/sdd/PROGRAM004R-real-audio-and-durable-playback-completion.md`
Amendment commit: `020afe43958212dade3cde8ad4c928e6ac6a423f`
Reviewed at: `dc93e848304e8e15156a64e56d8cebb7e1b8b132`
Branch: `program004r/real-audio-durable-playback`, based on PR #4 head `d1d0674`
Machine-readable evidence: `docs/evidence/PROGRAM004R/acceptance.v1.json`

## Disposition

```
SDD                = ACCEPTED_WITH_BINDING_AMENDMENTS_APPLIED
IMPLEMENTATION     = PARTIAL
NATIVE_INTEGRATION = NOT_RUN
ANDROID_DEVICE     = NOT_RUN
IOS_DEVICE         = NOT_RUN
HUMAN_LISTENING    = NOT_RUN
STORE_RELEASE      = BLOCKED
```

**IMPLEMENTATION is PARTIAL, not COMPLETE.** The production audio path, the
full-prepare readiness rule and the durable store all exist and are tested.
What is missing is stated in "Not done" below, and no amount of green CI
changes that: a session has never been played on a real device by this program,
and Slice E's durable feedback surface is not built.

## What each slice delivered

| Slice | Commit | Delivered |
|-------|--------|-----------|
| 0 | `020afe4` | SDD amendments A1–A8, alone |
| A | `a0e5bb3` | real native adapters, production bootstrap, bundled bells |
| B1 | `3c0a8a1` | resolutions with cross-language hashing, server validation, migration 0006 |
| B2 | `b927dbc` | full prepare, immutable audio cache, pins |
| C | `247c898` | the runtime owns completion; the ticker cannot |
| D1 | `c820b68` | command identity in the database, reconciliation, migration 0007 |
| D2 | `ff784b8` | durable local store against real SQLite |
| F | this commit | CI, evidence, status |

## The production call graph now

```text
main.dart
  └─ bootstrapAudioRuntime()                        platform/bootstrap.dart
       ├─ 1. NativeAudioSession.warmUp()   ← owns category and focus, first
       ├─ 2. NativeTtsProvider             ← must not reconfigure the session
       └─ 3. NativeAudioPlayer             ← owns neither interruptions nor
                                             activation
  └─ AdaptiveMeditationApp(adapters, player, mediaDirectory)

PrepareController.prepare()                  features/session/prepare_controller.dart
  ├─ describe()            → engine, voice, rate, encoding (unknowns as unknown)
  ├─ per speech segment: synthesizeToFile → publish (atomic) → decode probe
  ├─ per bell: bundled asset + recorded sha256
  ├─ re-verify every published file from disk
  ├─ pin every hash                          ← before ready, so LRU cannot take it
  └─ ResolvedTimeline (local) → resolution_hash
       └─ POST /v1/sessions/{id}/resolution  ← recorded, never a gate

PlaybackRuntime                              features/session/playback_runtime.dart
  ├─ load(playable)  → NativeAudioPlayer → just_audio (local file/asset URIs)
  ├─ lifecycle callbacks → coverage per required segment
  ├─ first speech start  → audioOutputStarted  ← voice exposure waits for this
  └─ full coverage       → sessionDelivered    ← the only path to completion

PlaybackController.reconcile()               ← refuses stale snapshots
DurableStore                                 ← checkpoints + outbox, quota-bounded
```

## Defects fixed in this program

1. **No audio in production** — `app.dart` omitted `tts:` and `audioSession:`,
   so a release build injected silent no-ops. Bootstrap now builds the real
   adapters in a fixed order, and a wiring test refuses any set containing a
   `Silent*`/`Fake*` type or a default-constructed one.
2. **Bells could not reach a device** — generated, hashed and CI-verified at the
   repository root with no `assets:` section. Moved into the Flutter package,
   declared, and a test asserts each one is bundled rather than merely present.
3. **Completion was a countdown** — `_tick()` called `_complete()` when a 200 ms
   ticker passed the planned total. The runtime owns completion now; the ticker
   only renders.
4. **`resolve_timing` had no caller** — fully tested, entirely unreachable. The
   resolution builder calls it, so a stored resolution's silence allocation
   comes from the arithmetic the tests pin.
5. **Select-then-insert command identity** — two concurrent retries both passed
   the check and both inserted. A unique constraint decides, with a savepoint
   for the loser. Proven with four concurrent retries.
6. **`adopt()` could regress the sequence** — the G6 hypothesis. Replaced by
   `reconcile()`, which refuses a stale snapshot, never moves position
   backwards, never revives a terminal run and never leaves a controller
   playing without a clock.
7. **Memory-only pending queue** — a Dart list on a `State`. Now sqflite with
   explicit quotas.
8. **`flutter_tts` "queued" read as "done"** — the plugin returns `1` for both.
   The adapter waits for the engine's completion signal and then still checks
   the file exists, is non-empty and hashes.
9. **`just_audio` auto-resume after interruption** — the plugin default. The
   player is constructed with `handleInterruptions: false`, so only a user
   action resumes.
10. **Two owners of the audio session** — `handleAudioSessionActivation: false`
    leaves exactly one.
11. **`audio_session`'s `AudioDeviceType` is experimental** and has no
    `usbHeadset`. Route detection matches enum names and degrades to `unknown`,
    which the privacy rule already treats as audible-to-the-room.
12. **`ConcatenatingAudioSource` deprecated** in just_audio 0.10.6; using
    `setAudioSources` with `preload: false`.
13. **`describe()` was gated on `Platform.isAndroid`** — untestable off-device
    for no benefit, since failure already fell through to the same default.
14. **A transitive permission no source manifest showed** —
    `ACCESS_NETWORK_STATE` from ExoPlayer, found by the merged-manifest audit
    in CI. Declared with attribution; see "Not done" for why it is not yet
    stripped.
15. **Undeclared SDKs** — the compliance gate failed until the inventory carried
    all six packages with their enabled network paths.
16. **A vacuous assertion** — `assert "." not in x.replace(".", "", 0) or True`
    in my own float test. Replaced with a check on the canonical string.
17. **A wrong test count** in a commit message (559 for 557), amended.

## G6

**CONFIRMED BY INSPECTION, NOT REPRODUCED.** Reproducing it needs the pre-fix
`adopt()`, which assigned any incoming sequence unconditionally; keeping that
method alive purely to fail a test would mean shipping the defect. My first
attempt simulated it with local variables, which asserted nothing about this
program — that is the fabricated red test the review warned against, and I
deleted it. What is tested instead is the guard driven through the exact
interleaving, plus the invariant that the run still accepts commands
afterwards, plus the server-side rule that an older command never lowers the
stored sequence.

## Evidence

Local, on the workstation named in the evidence file:

```
backend    557 tests, exit 0, PostgreSQL 16.15
flutter    194 tests, exit 0
ruff / ruff format / mypy      clean
flutter analyze --fatal-infos  clean
migrations 0006 and 0007       up, down one step, up; no pending diff
timing fixtures                current
bell provenance                current
compliance consistency         PASS
credential scan                clean
```

New test coverage by tier: **PLATFORM_CHANNEL** (the real TTS adapter against a
mocked OS), **REAL_SQL** (the durable store against real SQLite via
`sqflite_common_ffi`), plus unit, HTTP and widget.

16 acceptance cases: **9 PASS, 6 PARTIAL, 1 NOT_RUN**, each with its tier and
evidence path in `acceptance.v1.json`.

## Not done

1. **No device, no simulator, no emulator.** No full Xcode (Command Line Tools
   only), no Android SDK. `flutter devices` reports none. Every native tier is
   NOT_RUN, and **no platform may be called device-validated**.
2. **Nothing has been heard.** No human listening record exists, and no
   automated result substitutes for one.
3. **Slice E is partial.** Completion and exposure semantics are implemented and
   tested; durable feedback save, the pending-sync surface and the history
   projection of a pending completion are not built.
4. **Silence is not yet scheduled media.** Required silence counts toward
   readiness but the runtime does not yet play it as a bounded media source, so
   the long-silence-after-lock case (R06) has no implementation to test.
5. **Every device-side budget is NOT_RUN.** No workstation figure is
   substituted for a device figure.
6. **The release gate is not yet split** into the five axes A8 requires.
7. **`ACCESS_NETWORK_STATE` is declared rather than stripped.** The merged
   manifest audit found it contributed transitively by ExoPlayer through
   `just_audio` — nothing in this repository requests it and no plugin's own
   manifest declares it, which is exactly the case only a merged-manifest audit
   can catch. This app never gives the player a network source, so no enabled
   path reads it. Removing it with `tools:node="remove"` is the right end state
   and is deferred: ExoPlayer's network-type observer reads `ConnectivityManager`
   during initialisation on some versions, and stripping a permission a media
   engine may read is not a change to make with no device to verify it on.
8. **No OCI deployment**, no store upload, no signing, no merge.
