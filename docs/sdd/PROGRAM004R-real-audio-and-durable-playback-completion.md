# PROGRAM004R — Real Audio and Durable Playback Completion

**Task ID:** `PROGRAM004R_SDD_REAL_AUDIO_AND_DURABLE_PLAYBACK_COMPLETION`
**Type:** design contract. Authored SDD-only; amended under review; the
amendment commit is followed in the same task by the Slice A–F implementation
it specifies.
**Status:** reviewed at `dc93e848304e8e15156a64e56d8cebb7e1b8b132` and
**accepted with binding amendments**, applied in §6.1, §9.1, §11.4, §13 and
§13A. Where earlier text disagrees with §13A, §13A governs.
**Completes:** `docs/sdd/PROGRAM004-core-adaptive-meditation-experience.md`
(accepted at `44c4419365b9701ad2a9813159ca4a85dae18bc3`).
**Does not replace:** Program005 Personalization.

## 0. Label legend

Every claim in this document carries one of four labels. They are not
decoration: the distinction between "I read this in the code today" and "I
reasoned that this would happen" is the difference between an audit and a
guess.

| Label | Meaning |
|-------|---------|
| **FACT** | Observed this round by reading the tree at the stated SHA, or by querying the remote. A command or a file path is cited. |
| **DESIGN_DECISION** | A choice this SDD makes and commits to. Binding on the implementation package unless a review overturns it. |
| **PROPOSED_ACCEPTANCE** | A test or threshold this SDD proposes. Not yet written, not yet run. |
| **NOT_RUN** | Known to be unverified, with the reason. Includes everything needing a physical device. |

Nothing in this document describes a designed capability as a completed one.
Section 3 exists precisely to prevent that reading.

## 1. Re-verified remote baseline

**FACT.** Re-read this round rather than carried forward. The previous round's
values are listed beside them; where they agree, that is a verified match, not
an assumption.

| Item | Value (this round) | Previous round | Agrees |
|------|--------------------|----------------|--------|
| `origin/main` | `ec82f883701e6e7ae4fa94075c6bf541f70ae75c` | same | yes |
| PR #3 state | `OPEN`, `mergedAt=null`, `mergeCommit=null` | OPEN | yes |
| PR #3 head | `a75b6ca1ccde1d2592dc588e9597ee93d0fadd7d` | same | yes |
| PR #4 state | `OPEN`, `mergedAt=null`, `mergeCommit=null` | OPEN | yes |
| PR #4 head | `d1d06742a9f5506161559b7f79ee054fb80bf115` | same | yes |
| Accepted Program004 SDD | `44c4419365b9701ad2a9813159ca4a85dae18bc3` | same | yes |

**FACT — neither PR is merged.** `gh pr list --json mergedAt,mergeCommit`
returns `null` for both on #3 and #4. Both do carry a
`potentialMergeCommit` — #3 `4a37dfbe0d1268e449961dc98bc6bf243ad89bcf`, #4
`727e89f830bfd6b2126bd77e12920123e63d9da6`. **These are synthetic refs GitHub
computes for the checks; they are not merges and their existence says nothing
about merge status.** `main` is still `ec82f883`, which predates every
Program004 commit.

### 1.1 CI: two runs per commit, and they check different trees

**FACT.** Each push to the branch produced two runs, on different events, with
different checkouts:

| Run | Event | Checked-out tree | Backend tests | Jobs |
|-----|-------|------------------|---------------|------|
| `34682972290` | `push` | `d1d0674` — the branch head itself | `522 passed, 1 warning` | 6/6 success |
| `34682973745` | `pull_request` | `727e89f8` — **synthetic merge of `d1d0674` into `ec82f883`** | `522 passed, 1 warning` | 6/6 success |

The `pull_request` run's checkout step logs
`HEAD is now at 727e89f Merge d1d06742a9f5506161559b7f79ee054fb80bf115 into
ec82f883701e6e7ae4fa94075c6bf541f70ae75c`.

**FACT — a correction to the previous round's report.** That report cited run
`34682973745` alone as the evidence run. That run validates the *merge result*,
not the branch head in isolation. Both runs are green and both report 522
passed, so the conclusion survives; the citation was imprecise. Program004R
records both, and the implementation package requires both to be cited
separately at closure (Slice F).

### 1.2 Branch for this round

**FACT.** PR #4 is unmerged, so this SDD branches from the re-verified #4 head:

```
git checkout -b program004r/real-audio-durable-playback-sdd d1d06742a9f...
```

Verified clean at creation. No force-push, no rewrite of anyone's work, no
modification to any file outside the single new document.

## 2. What this round does and does not touch

**FACT — permitted and used:** create `program004r/real-audio-durable-playback-sdd`;
add exactly one file, `docs/sdd/PROGRAM004R-real-audio-and-durable-playback-completion.md`;
commit; push; read back the remote SHA.

**FACT — not touched:** implementation, tests, migrations, dependencies,
platform manifests, `docs/sdd/PROGRAM004-core-adaptive-meditation-experience.md`,
`docs/PROGRAM004_STATUS.md`, any PR description. PRs #3 and #4 are not merged.
No OCI deployment, no store asset, no paid service.

## 3. The honest state of Program004

This section exists because the previous round's closure could be misread as
"complete, pending merge". It is not. What exists is a correct, tested
**foundation** whose product-facing half is not wired up.

### 3.1 Backend module reachability

**FACT.** Measured on `d1d0674` by searching `backend/app` for importers of each
Program004 module, excluding the module itself and excluding tests:

| Module | Production importers | Reachable from an HTTP request? |
|--------|---------------------|--------------------------------|
| `domain/audio/render.py` | `adapters/audio/{fake,registry}.py`, `persistence/{models,repositories}.py`, `api/v1/routes.py`, `domain/audio/coordinator.py` | **yes** |
| `domain/audio/coordinator.py` | `api/v1/routes.py` | **yes** |
| `domain/playback/state_machine.py` | `api/v1/routes.py`, `domain/timeline/service.py`, `domain/playback/routing.py` | **yes** |
| `domain/timeline/timing.py` | **none** | **no** |
| `domain/playback/clock.py` | **none** | **no** |
| `domain/playback/scheduler.py` | **none** | **no** |
| `domain/playback/routing.py` | **none** | **no** |
| `domain/playback/failures.py` | **none** | **no** |
| `domain/audio/cache.py` | **none** | **no** |
| `domain/audio/capability.py` | **none** | **no** |

**Seven of ten modules have no production caller.** They are fully tested and
entirely unreachable. This is the "framework with no production caller" the
Program004R brief warns against, and Program004R created it. Every one of the
seven is either given a real consumer by the implementation package below or
deleted; none is left as tested dead code.

The client holds parallel Dart implementations of four of them — the state
machine (`playback_controller.dart:48`), the scheduler and resume rule
(`core/timeline.dart` `segmentAt` / `resumePosition`), and the route policy
(`platform/audio_session.dart` `interruptionForRouteChange`). So the *behaviour*
partly exists, in a second language, with no shared fixtures. Section 7.4
addresses that directly.

### 3.2 The production call graph as it exists today

**FACT.** Traced from `main.dart` through to feedback on `d1d0674`. `✗` marks a
step that does not happen.

```text
main.dart
  └─ AdaptiveMeditationApp
       └─ PlatformAdapters(storage: …)            app.dart:32
            ├─ tts:          (omitted) ──▶ SilentTtsProvider   ✗ speak() is a no-op
            └─ audioSession: (omitted) ──▶ SilentAudioSession  ✗ never interrupts
                                                               ✗ route always unknown
RecommendationScreen._start
  └─ POST /v1/sessions ────────────────────▶ plan_v2 + plan_hash          ✓ real
       └─ PlayerScreen (typed plan present)                                ✓ real
            └─ _prepareAndStart                     player_screen.dart:123
                 ├─ _send(prepare)                 ──▶ POST …/playback     ✓ real
                 ├─ await _api.prepareSession(id)  ──▶ POST …/prepare      ✓ call made
                 │     └─ RenderManifest returned  ──▶ RESULT DISCARDED    ✗ not assigned
                 │        (entries, unresolved, content_sha256 all unread)
                 ├─ _send(resolved) ── unconditional ─▶ state = ready      ✗ no audio check
                 └─ _start
                      ├─ audioSession.activate() ──▶ SilentAudioSession → always true
                      ├─ _send(start) ──▶ state = playing
                      └─ Timer.periodic(200 ms) ──▶ _controller.tickTo()
                            └─ reachedEnd → _complete()                    ✗ countdown only
                                                                           ✗ nothing was spoken
            └─ _complete
                 ├─ _send(complete) ──▶ POST …/playback                    ✓ real
                 ├─ _flush() ──▶ POST …/events (memory queue)              ✓ real, but
                 │                                                          ✗ memory-only
                 └─ FeedbackScreen ──▶ POST …/feedback                     ✓ real
```

**FACT — the product consequence.** In a release build today, a session is a
600-second silent countdown. The backend correctly records `session_started`,
`segment_started` and `session_completed`; the plan is frozen and reproducible;
the journal is honest about what the client told it. Nothing in that chain is
false — but no sound is ever produced, and the recorded completion describes a
timer expiring, not a meditation being listened to.

### 3.3 Assets exist but are not deliverable

**FACT.** `assets/audio/bells/{opening,closing,transition}.wav` exist, are
generated by `scripts/generate_bells.py`, are hash-pinned in
`assets/audio/PROVENANCE.json`, and are byte-for-byte verified in CI.

**FACT.** `apps/mobile/pubspec.yaml` contains **no `assets:` section**. No Dart
code references any bell file, an `AssetBundle` or `rootBundle`. `assets/` sits
at the repository root, outside the Flutter package, so it cannot be listed in
`pubspec.yaml` as-is.

**The bells therefore cannot reach a device and cannot be played.** The
provenance test proves the files exist in the repository and match their
generator. It proves nothing about delivery, and must never be cited as
playback evidence.

### 3.4 Declared vocabulary with no producer

**FACT.** These event types are in the closed set enforced by
`SESSION_EVENT_TYPES` and by the `ck_session_events_type` database constraint,
and **nothing anywhere emits them**: `timeline_extended`, `timeline_compressed`,
`timeline_drift_exceeded`, `silent_mode_used`, `render_cache_hit`,
`render_cache_miss`. `route_changed` is produced only by
`domain/playback/routing.py`, which itself has no production caller (§3.1).

Silent mode is named in the event set and nowhere else: there is no silent-mode
flag, setting, state or code path. **FACT.**

## 4. Gap matrix against the accepted SDD

Columns: what the accepted SDD requires; what calls it today; the gap; the
strongest evidence that exists now; the completion this SDD commits to; and the
acceptance test that will prove it.

### G1 — No real audio provider is wired in production

| | |
|---|---|
| **Required** | §8.4: "Provider-neutral runtime. First shipped provider: device-native TTS." |
| **Current caller** | `app.dart:32` builds `PlatformAdapters(storage: …)`. `tts:` and `audioSession:` are omitted, so defaults apply. **FACT** |
| **Gap** | `SilentTtsProvider.isSupported == false` and `speak()` is `async {}`. `SilentAudioSession.activate()` always returns `true`, `currentRoute()` always returns `unknown`, and its three streams never emit. A release build has no audio path at all. **FACT** |
| **Evidence today** | Flutter widget tests drive a `FakeAudioSession`. No test asserts what production injects. **FACT** |
| **Completion** | Slice A. Real `TtsProvider` and `AudioSessionPort` implementations, injected by default; the silent implementations become explicitly-selected test doubles. |
| **Acceptance** | A release-mode wiring test asserting the default adapter set contains no type whose name matches `Silent*` or `Fake*`. **PROPOSED_ACCEPTANCE** |

### G2 — `resolved` is sent regardless of whether any audio exists

| | |
|---|---|
| **Required** | §5.2: `preparing → ready` only when "every segment has audio or an accepted fallback". |
| **Current caller** | `player_screen.dart:123-131`. **FACT** |
| **Gap** | `await _api.prepareSession(...)` is called, its `RenderManifest` return value is **not assigned to anything**, and `_send(RunCommand.resolved)` runs unconditionally — including from inside the `on ApiException` recovery path. `unresolved`, `entries` and `content_sha256` are parsed by `models.dart` and discarded. There is no per-segment readiness check anywhere in the client. **FACT** |
| **Evidence today** | `test_audio.py::test_prepare_returns_a_manifest` asserts the server's response shape. Nothing asserts the client acts on it. **FACT** |
| **Completion** | Slice B. `ready` requires a per-segment resolution record, each with a verified local file or an explicitly accepted fallback rung. |
| **Acceptance** | Prepare fails / no voice / corrupt cache / disk full ⇒ never `ready`; state is `failed` with a `FailureCode`, or `ready` in an explicitly recorded degraded mode. **PROPOSED_ACCEPTANCE** |

### G3 — Completion is a countdown, not evidence of playback

| | |
|---|---|
| **Required** | §5.3 and §17.1: `session_completed` means the session was delivered. |
| **Current caller** | `player_screen.dart:172-176`: `_tick()` → `if (_controller.reachedEnd) _complete()`. `reachedEnd` is `_positionMs >= plan.totalMs`. **FACT** |
| **Gap** | The only input is a `Timer.periodic(200 ms)` advancing a counter. No audio callback, no segment-completion signal, no check that the closing bell or the final speech segment ever played. With `SilentTtsProvider` in production, **every** completed session is a silent timer. |
| **Evidence today** | Widget tests assert the countdown behaviour, which is faithful to what the code does. **FACT** |
| **Completion** | Slice C. The player/background service is the segment lifecycle authority; the UI timer may only render. `session_completed` requires the final required segment to have reported completion, or an explicit silent-mode/abandonment record. |
| **Acceptance** | A session whose audio never starts cannot reach `completed` as an audible completion; it records `silent_mode_used` or `playback_failed` with a reason. **PROPOSED_ACCEPTANCE** |

### G4 — `resolve_timing` has no production caller

| | |
|---|---|
| **Required** | §6.4 as corrected: real durations feed back and elastic silence absorbs overrun. |
| **Current caller** | None. `grep` across `backend/app` finds references only in `tests/test_timeline.py`. **FACT** |
| **Gap** | The arithmetic is correct and thoroughly tested against its boundaries, and nothing has ever called it with a measured duration, because nothing measures one. §9.3's "durations feed back" loop does not exist. |
| **Evidence today** | Nine unit tests. **FACT** |
| **Completion** | Slice B/C. Real synthesis produces measured durations; a resolved playback timeline is computed from them (§7) and persisted; the client consumes the same resolution. |
| **Acceptance** | A session whose measured speech exceeds its estimate produces a persisted resolution with non-zero `absorbed_ms`, and the UI's remaining time matches it. **PROPOSED_ACCEPTANCE** |

### G5 — Pending events live only in memory

| | |
|---|---|
| **Required** | §5.3: "App killed during silence — journal holds the last confirmed segment boundary. On relaunch, offer resume from that boundary." |
| **Current caller** | `playback_controller.dart`: `final List<PlaybackEvent> _pending = <PlaybackEvent>[]`. **FACT** |
| **Gap** | A Dart list on a `State` object. Nothing is written to disk. Navigating away disposes it; the OS killing the app discards it. Recovery today works only because the *server* holds state — which requires the network, contradicting §20's offline contract. An offline kill loses everything since the last successful request. |
| **Evidence today** | `test_program004_e2e.py::test_a_session_survives_the_client_dying_mid_playback` proves the **server** can answer a recovery query. It does not exercise a client restart. **FACT** |
| **Completion** | Slice D. A real local durable store (§9). |
| **Acceptance** | Airplane mode, play, kill, relaunch: resume at the confirmed boundary and the unsent queue is still present. **PROPOSED_ACCEPTANCE**, device tier. |

### G6 — Concurrent commands: state, journal and ACK consistency

| | |
|---|---|
| **Required** | §5.4 idempotency; journal as reconstruction evidence. |
| **Current caller** | `player_screen.dart:208` `unawaited(_deliver(command, event))`. **FACT** |
| **Gap (read from code, labelled below)** | Three concerns, at different confidence levels. |

**FACT (structural, read directly):**
- `_deliver` calls `_controller.acknowledge([event])` **before** examining
  `state.applied` (`player_screen.dart:223`, then `:224`). A command the server
  dropped as out-of-order is removed from the client queue and was never written
  to the server journal, so **no record of it exists anywhere**.
- `_flush`'s failure path does not re-queue and does not acknowledge; the
  comment says "Dropped rather than retried forever" while the code leaves the
  events in a `_pending` list on a `State` about to be disposed. Outcome and
  comment agree by accident, not by mechanism.

**PLAUSIBLE — NOT_RUN, must be reproduced before it is fixed or dismissed:**
- Because deliveries are `unawaited`, responses may arrive out of order. `_adopt`
  assigns `sequence: state.commandSequence` unconditionally. A late response
  carrying an *older* `command_sequence` would therefore move the client's
  sequence **backwards**, after which the next command reuses a number the
  server has already seen and is dropped as a replay. This is read from the
  code, not observed. Slice D must write the failing test first.

| | |
|---|---|
| **Completion** | Slice D. Single-writer command queue, ACK only after a response that confirms application, reconciliation that can never lower a sequence. |
| **Acceptance** | Interleaved/duplicated/reordered responses under fault injection leave state, journal and ACK mutually consistent. **PROPOSED_ACCEPTANCE** |

### G7 — No native audio evidence exists at any tier

| | |
|---|---|
| **Required** | Product acceptance: a person hears a guided meditation. |
| **Evidence today** | 522 backend tests (HTTP + domain), 107 Flutter tests (widget + unit, all against fakes). Real iOS and Android **release builds** succeed in CI. **FACT** |
| **Gap** | No simulator/emulator audio test, no real-device run, no listening record. A release build compiling proves it links, not that it speaks. |
| **Completion** | Slice F defines the tiers and what each may claim. |
| **Acceptance** | Per §11.2, device tiers are **NOT_RUN** until a device exists; `device-validated` may not be claimed for a platform without one. |

### G8 — Reported numbers and capability language must stay exact

| | |
|---|---|
| **FACT** | PR #4's body says "523 backend tests"; `docs/PROGRAM004_STATUS.md` says 522; `pytest --collect-only` reports **522**; both CI runs report **522 passed**. The 523 came from counting pytest progress characters with a regex that matched an extra line. The status document was corrected in `d1d0674`; **the PR body still says 523.** |
| **FACT** | The status document cites CI `34682585387`+`34682973745` without distinguishing the `push` checkout from the `pull_request` synthetic-merge checkout (§1.1). |
| **Completion** | Slice F, at closure, in one pass: PR body, status document, CI citations split by event, and every capability sentence re-read against §3. This round does not edit them — it is SDD-only. |
| **Acceptance** | A closure checklist item: every number in a delivery artefact is reproducible by a stated command. **PROPOSED_ACCEPTANCE** |

### G9 — The release gate conflates toolchain presence with build success

| | |
|---|---|
| **FACT** | `scripts/store_release_gate.py:192-207` marks **"iOS release compile" PASS when `subprocess.run(["xcodebuild","-version"]).returncode == 0`**. That is toolchain availability. A machine with Xcode installed and a completely broken project reports PASS. |
| **FACT** | `:180-187` marks "Android release AAB builds" PASS if a file exists at `apps/mobile/build/app/outputs/bundle/release/app-release.aab`. A stale artefact from any earlier build passes. Nothing binds either check to a commit SHA. |
| **FACT — and not to be conflated** | CI genuinely builds both: `.github/workflows/ci.yml:254` runs `flutter build ios --release --no-codesign` and then asserts `PrivacyInfo.xcprivacy` is inside the built `.app`; `:192` runs `flutter build appbundle --release` and audits the **merged** manifest. **A real iOS release compile does succeed, in CI, on the checked-out SHA.** The gate simply does not consume that evidence. |
| **Gap** | Two different claims share one label, and the weaker one is the one the gate reports. |
| **Completion** | Slice F splits the gate into five independent axes (§12.2). |
| **Acceptance** | `toolchain_available` and `candidate_build_verified` are separate rows; the latter requires a SHA-bound artefact. Removing signing/identity blockers must not be able to produce `STORE_READY`. **PROPOSED_ACCEPTANCE** |

## 5. Audio technology decision

The brief requires one default approach, chosen now.

### 5.1 The pipeline, decided

**DESIGN_DECISION.** Prepare-time synthesis to a local file, verified, then
played by a background-capable file player:

```text
prepare:  text ──▶ native TTS synthesizeToFile ──▶ local file
                        ├─ measure real duration
                        ├─ hash bytes → audio_sha256
                        └─ decode-probe: the file opens and reports a duration
play:     local files + bell assets ──▶ background audio player
```

Speaking text directly through a TTS engine at playback time is rejected:
duration would be unknowable in advance, the elastic-silence arithmetic would
have nothing to work with, background reliability would depend on an engine we
do not control, and nothing could be hash-verified or replayed. Synthesis is a
prepare-time cost, exactly as §8.1 of the accepted SDD argues.

### 5.2 First-party bridge versus plugins

**FACT — package data, queried from pub.dev this round:**

| Package | Version | Published | Pub points | Likes | Licence |
|---------|---------|-----------|-----------|-------|---------|
| `just_audio` | 0.10.6 | 2026-06-29 | 150/160 | 4147 | Apache-2.0 / MIT |
| `audio_service` | 0.18.19 | 2026-06-29 | 140/160 | 1331 | MIT |
| `audio_session` | 0.2.4 | 2026-06-29 | 150/160 | 363 | MIT |
| `flutter_tts` | 4.2.5 | 2026-01-05 | 150/160 | 1598 | MIT |
| `sqflite` | 2.4.4 | 2026-09-10 | 160/160 | 5564 | BSD-2-Clause |
| `path_provider` | 2.1.6 | 2026-06-15 | 160/160 | 5565 | BSD-3-Clause |

All are permissively licensed, all are compatible with the pinned Flutter
3.47.3 / Dart 3.13.3 toolchain, and none phones home.

| Criterion | First-party Swift/Kotlin bridge | Minimal maintained plugin set |
|-----------|-------------------------------|------------------------------|
| Completion cost | High. Android media foreground service, `MediaSession`, notification, `MediaBrowserService` reconnection, iOS remote commands and Now Playing are each a well-known source of subtle bugs. | Low for the solved parts. |
| Maintenance cost | Every OS behaviour change is ours. | Upstream absorbs most of it; we absorb version churn. |
| Background reliability | Depends entirely on getting the service lifecycle right the first time. | This is precisely what `audio_service` exists for and is the most-exercised path in it. |
| Version support | Ours to track. | Declared, and verifiable at pin time. |
| Package size | Smallest. | Modest; `just_audio`/`audio_service` add no large binary. |
| Licensing | n/a | Permissive throughout (above). |
| Data flow | None. | None. No package above performs analytics or network calls of its own. |

**DESIGN_DECISION — hybrid, weighted to plugins for background playback.**

- **Background playback and media session:** `audio_service` + `just_audio`.
  Rationale: this is the highest-risk, lowest-differentiation code in the
  program. A first-party Android foreground-service implementation would be
  several hundred lines whose failure mode is "playback silently dies in the
  user's pocket" — the exact failure a meditation app cannot have, and the one
  hardest to catch without a device farm.
- **Focus and route:** `audio_session` (already `audio_service`'s dependency),
  behind the **existing** `AudioSessionPort` interface. The port stays; only its
  implementation arrives.
- **Synthesis to file:** `flutter_tts` `synthesizeToFile`, behind the
  **existing** `TtsProvider` interface, extended per §5.3.
- **Local durable store:** `sqflite` + `path_provider` (§9.1).

**Zero new dependencies is explicitly not the goal.** Program004 achieved zero
dependencies and produced an app that cannot make a sound. Reliable completion
of the user flow is the goal.

**Rejected:** a pure first-party bridge (cost concentrated in exactly the
riskiest area); `flutter_local_notifications` for media controls
(`audio_service` owns the notification, and two owners is a defect);
platform-channel-free playback (no such thing for background audio).

**NOT_RUN.** Exact version pinning happens in Slice A against the criteria
above, re-queried at that time. The versions in the table are what pub.dev
reported this round and are evidence for the decision, not a pin.

**FACT — `flutter_tts` capability caveat.** `synthesizeToFile` is supported on
both platforms, but iOS support depends on `AVSpeechSynthesizer.write`
(iOS 13+), and engine availability on Android varies by device and by the user's
configured engine. Slice A must therefore treat "this device can synthesise to a
file" as a **runtime probe result**, never a build-time assumption — which is
what `OfflineCapability` (§3.1, currently uncalled) already exists to express.

### 5.3 The port contract, extended

**DESIGN_DECISION.** `TtsProvider` gains a file-producing operation; the
existing interface is extended, not replaced:

```dart
abstract interface class TtsProvider {
  bool get isSupported;
  TtsOfflineCapability get offlineCapability;   // already exists

  /// Probe what this device can actually do. Runtime, never assumed.
  Future<TtsEngineDescriptor> describe();

  /// Synthesise to a local file. Returns the measured duration and byte hash.
  Future<SynthesisResult> synthesizeToFile(SynthesisRequest request);

  Future<void> stop();
}
```

`TtsEngineDescriptor` carries `engineId`, `voiceId`, `locale`, `rate`, `pitch`,
`engineVersion` and `encoding` — every input that can change output bytes.

**DESIGN_DECISION — the audio player port is new and first-party:**

```dart
abstract interface class AudioPlayerPort {
  Future<void> load(ResolvedTimeline timeline);
  Future<void> start();      Future<void> pause();
  Future<void> resume();     Future<void> stop();
  Future<void> dispose();
  Duration get position;     Duration? get duration;
  Stream<SegmentLifecycleEvent> get lifecycle;   // started / completed / error
  Stream<PlaybackFault> get faults;
}
```

**DESIGN_DECISION — the four states that are not the same thing**, each with its
own event, because collapsing them is how "completed" comes to mean nothing:

1. **Enqueued** — a synthesis request was accepted. Proves nothing.
2. **Synthesised** — a file exists, hashes, and decode-probes to a duration.
3. **Playback reported complete** — the player says the segment finished.
4. **Heard** — *not observable*. No automated test may assert it; §11.3's
   listening record is the only evidence, and it is a human record.

**DESIGN_DECISION — three distinct silent situations**, never merged:

| Situation | Meaning | Recorded as |
|-----------|---------|-------------|
| Test double | `FakeTts` / `FakeAudioSession` in a test | never in production; wiring test forbids it |
| Device cannot | No engine, no voice, synthesis fails | `render_failure` + degraded mode, user told |
| User chose | Silent mode selected deliberately | `silent_mode_used`, a first-class mode |

A production audio mode may never resolve to a test stub. **PROPOSED_ACCEPTANCE:**
the release wiring test in G1.

### 5.4 Bell assets must actually ship

**DESIGN_DECISION.** Slice A moves the generated bells to
`apps/mobile/assets/audio/bells/` and declares them in `pubspec.yaml`, keeping
`scripts/generate_bells.py` and `PROVENANCE.json` as the generator and the
record. The generator's output path changes; its determinism and CI check do
not.

**PROPOSED_ACCEPTANCE:** every `BellSegment.asset_key` in a plan resolves to a
bundled asset that loads and reports a non-zero duration on device — and the
opening, transition and closing bells each have a real consumer in the resolved
timeline. Presence in the repository, and a green provenance check, are
explicitly **not** acceptable as playback evidence.

**Excluded, per the brief:** real-time cloud synthesis; any model choosing a
practice; any paid TTS account as a dependency of this completion.

## 6. Ready, cache and offline capability

### 6.1 What `ready` is allowed to mean

**AMENDED A1 — the normative definition.** Exactly one readiness model:

```text
AUDIO_READY =
      canonical plan and content available locally
  AND every required speech / bell / silence medium locally resolvable
  AND hashes, container format, measured duration and decode probe all pass
  AND resolved timeline persisted locally
  AND every required asset reference pinned
  AND the production playback adapter initialised without error
```

Every one of those clauses is necessary. `preparing → ready` happens once, for
the whole required set, and not before.

Focus and route are **not** part of readiness — they are checked at `start`,
because they are conditions of the moment rather than properties of preparation.

**Full verification does not mean everything stays resident.** Each file is
decode-probed and then released; playback uses a bounded buffer. A 20-minute
session is never decoded into RAM as PCM. §11.4's memory budget governs this.

**Warm-up is allowed; synthesis after `start` is not.** The recommendation
screen may pre-warm the *current candidate* early and cancellably, showing
progress. Once `ready` is reached, no required segment may still be
synthesising. Pre-warming must not sweep every practice and voice.

**DESIGN_DECISION — explicitly insufficient for `ready`:** that the prepare API
was called; that a manifest was received; that an exception was caught; that a
cache entry exists without hash verification. G2 is precisely the first and
third of these.

Bells count as required segments. Silence and markers require nothing.

### 6.2 Cache contract

**DESIGN_DECISION**, extending §9.2 of the accepted SDD, whose 150 MB soft cap
and 90-day staleness rule are carried over unchanged:

| Concern | Rule |
|---------|------|
| Atomic write | Synthesise to `<key>.part`, fsync, verify hash, then rename. A crash can leave `.part` files, never a corrupt-but-named entry. |
| Corrupt file | Hash mismatch on read ⇒ delete and re-synthesise. Never played. |
| Disk full | Fail the segment with `STORAGE_EXHAUSTED`, degrade per §9.4's chain, tell the user. Never a partial file presented as ready. |
| Cancellation | Prepare is cancellable; partial files are removed on cancel and on next start-up sweep. |
| Retry | Bounded with backoff, per `FAILURE_POLICY` — which finally gets a caller. |
| Concurrent dedupe | One in-flight synthesis per `render_key`; concurrent requesters await the same future. |
| LRU | Unchanged: 150 MB soft cap, stale-first, then least-recently-used. |
| Pinning | Files for a `ready` or `playing` run are pinned and **never** evicted. |
| Over-cap pinned set | If the pinned working set alone exceeds the cap, prepare **fails loudly at prepare time** with a capacity error. It does not silently exceed the cap, and it does not start a session it cannot hold. |
| Version invalidation | Key change is invalidation; nothing is mutated in place. |

### 6.3 Two hashes, two different questions

**DESIGN_DECISION.**

- `render_key` — **input fingerprint**: sha256 over normalised text, locale,
  voice, style, provider id, provider version, render version (SDD §9.1, already
  implemented). Answers "what was asked for?"
- `audio_sha256` — **output fingerprint**: sha256 of the produced bytes.
  Answers "what did we get?"

**It must not be assumed that native TTS is deterministic.** The same request on
the same device across an OS update may produce different bytes. Therefore:
`render_key` identifies a cache slot; `audio_sha256` validates the file in it.
A slot whose file no longer matches its recorded hash is re-synthesised, not
played. The key binds engine id, voice id, locale, rate/pitch/style, engine
version, render-contract version and encoding parameters — §5.3's
`TtsEngineDescriptor` is exactly that tuple.

### 6.4 Two offline capabilities, which do not imply each other

**DESIGN_DECISION.** The existing `OfflineCapability` enum (§3.1: no production
caller) is kept and given one, alongside a new and separate session-scoped
capability:

| Capability | Means | Established by |
|-----------|-------|----------------|
| `PREPARED_SESSION_OFFLINE_PLAYABLE` | *This* session's required audio is local and verified; it will play with the network off. | Per-segment verification at `ready` (§6.1). |
| `VOICE_LOCAL_CONFIRMED` | *This* engine/voice/config genuinely completed a **new** synthesis with the network unavailable. | A deliberate probe with connectivity disabled. |

**The first never implies the second.** A session that plays offline from cache
says nothing about whether the engine can synthesise offline — it did not try. A
cache hit is not a probe. This distinction is the whole content of the accepted
SDD's second correction, and conflating them would reintroduce the error.

Locale support keeps the two separate contracts already implemented in
`LocaleSupport`: approved content, and voice capability.

### 6.5 Silent mode

**DESIGN_DECISION.** Silent mode is a **deliberately selectable complete mode**,
not only a failure state: transcript on screen, silences timed, bells optional.
`silent_mode_used` gets its first producer.

When silent mode is entered by **degradation** rather than by choice, the app
tells the user why, and the journal records the reason and the mode. Such a
session is **not** recorded as an audible completion, and **does not** count as
exposure for any voice-related experiment.

## 7. Real duration and playback authority

### 7.1 Two timelines, both immutable, with different jobs

**DESIGN_DECISION.** `SessionDefinition` and the canonical `plan_hash` stay
exactly as they are — frozen, content-addressed, reproducible. A second artefact
is added:

```text
SessionDefinition (frozen content)      →  definition_id
        │
SessionPlanV2 (canonical intent)        →  plan_hash        [unchanged]
        │
        ├─ measured audio durations + audio_sha256 per segment
        ├─ timing_policy_version
        └─ resolve_timing()                                 [G4 closes here]
        ▼
ResolvedPlaybackTimeline                →  resolution_hash  [new]
```

The resolution references `plan_hash`, carries the measured durations and output
hashes, names the timing-policy version, and hashes to its own id. The plan says
what was intended; the resolution says what was actually playable. Replay of a
historical session uses the resolution when one exists and the plan when it does
not — which is how sessions recorded before Program004R stay interpretable.

### 7.2 How `resolve_timing` reaches production

**DESIGN_DECISION.** Slice B: after synthesis, the client holds a measured
duration per speech segment. It calls the resolution routine with them, producing
a `ResolvedPlaybackTimeline`, and `POST`s it with the session. The server
validates it against the plan (same segment ids, no silence below floor, no
negative silence), computes the `resolution_hash`, and persists it. The client
plays the resolution; the server can replay it; both agree because there is one
artefact.

### 7.3 Four durations that are not the same number

**DESIGN_DECISION.** Never conflated, each separately recorded:

| Quantity | What it measures |
|----------|------------------|
| Synthesis elapsed | How long producing the audio took. A prepare-cost metric; never part of session duration. |
| Audio content duration | How long the file plays. The input to timing resolution. |
| Wall playback time | Real time spent playing, excluding pauses. |
| Paused / interrupted time | Excluded from playback position; recorded separately. |

Session position is **playback time**, as `PlaybackClock` already implements —
and, per §3.1, does not yet call.

### 7.4 One arithmetic, two languages

**FACT.** The rule is implemented in Python (`domain/timeline/timing.py`, tested,
uncalled) and the player is Dart. Requiring Dart to execute Python is not
proposed.

**DESIGN_DECISION.** A shared, version-controlled **golden fixture set**:
`timing_fixtures.v1.json`, holding input timelines and measured durations with
their expected resolutions and hashes. Both implementations are tested against
the same file, and the fixture file carries the `timing_policy_version` that the
resolution record cites. A change to the arithmetic requires a new version and a
new fixture set; the two implementations cannot drift silently, because drift
fails a test on whichever side moved.

The same treatment applies to the other duplicated rules identified in §3.1:
state transition table, segment scheduling, resume position, route policy.

### 7.5 Shrinking rules, unchanged and now enforced at runtime

**DESIGN_DECISION**, inherited from the accepted SDD's first correction:
only silence that is **not yet consumed** and **is shrinkable** may be reduced;
never negative; never below `min_ms`; never truncate an utterance; never rewrite
already-played time. When the overrun exceeds available slack, the session is
**extended**, `extended_by_ms` is recorded, and `remaining`, `progress`, resume
point and backend replay all reflect the extension consistently.

### 7.6 Who owns the segment lifecycle

**DESIGN_DECISION.** The **audio player / background service** is the authority.
It emits `segment_started` and `segment_completed` from real playback callbacks.

The Flutter UI timer may only interpolate position **for display between
callbacks**. It may not advance state, may not complete a segment, and may not
produce an audible completion without a completion signal. G3 is exactly the
violation of this rule.

## 8. Native background playback

### 8.1 Ownership

**DESIGN_DECISION.**

| Layer | Owns | Must not |
|-------|------|----------|
| Flutter UI | Rendering, user intent, transcript, accessibility | Own the clock; decide completion; hold audio resources |
| Background runtime (`audio_service`) | Session lifecycle across backgrounding, media session, notification / Now Playing, remote commands | Contain product rules |
| Native player (`just_audio`) | Decoding, position, segment callbacks | Know about sessions or plans |
| Durable layer (§9) | Checkpoint, outbox, crash consistency | Block audio stop |

### 8.2 iOS

**DESIGN_DECISION.** A real `AVAudioSession` with the `.playback` category,
activated at `start` and deactivated when leaving the player; interruption
notifications (`began` / `ended`) mapped to the port's interruption stream;
route-change notifications mapped to the route stream with the old-device reason;
`MPNowPlayingInfoCenter` populated with title and elapsed/total; `MPRemoteCommandCenter`
play/pause wired to the same commands the UI issues.

`UIBackgroundModes: audio` is already declared **FACT** — and a declared key with
no session activation is precisely the "manifest key ≠ background playback"
error the brief names.

### 8.3 Android

**DESIGN_DECISION.** Real `AudioManager` focus request with
`AUDIOFOCUS_GAIN`; `AudioFocusRequest` listener mapped to the interruption
stream; `MediaSessionCompat` with playback state and metadata; a
`mediaPlayback` foreground service started when playback starts and stopped when
it ends; a media notification with play/pause; `ACTION_AUDIO_BECOMING_NOISY`
mapped to the headphone-disconnect rule.

`FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_MEDIA_PLAYBACK` are already
declared **FACT**, with no service to use them.

### 8.4 The cases that actually break

**DESIGN_DECISION.** Each is a named acceptance case in §11.1:

- **Long silence** (up to ~8 minutes in a 20-minute session): the service must
  not be reclaimed. Silence is scheduled as real playback, not as a sleeping
  timer.
- **Next segment after lock** — the case a timer-driven implementation fails
  invisibly.
- **UI disposed while playing**: the service continues; the UI re-attaches to
  the running session on return, and does not create a second one.
- **Service recreated by the OS**: rebuild from the durable checkpoint, not
  from UI state.
- **Duplicate callbacks**: segment-completion handling is idempotent per
  `(segment_id, occurrence)`.

### 8.5 Stop sound first, record second

**DESIGN_DECISION.** On focus loss, or a route change that would make audio
audible to the room, **the audio stops first**; the state change and journal
entry follow. The user must never hear a meditation in a room because a write
was in flight. Focus regained leaves the run **paused**; the user resumes.

**DESIGN_DECISION — `interrupted` resolved.** The accepted SDD §5.1/§5.2 model
`interrupted` as a distinct state with `playing --focus_lost--> interrupted`
**FACT**. The implementation collapsed it to `PLAYING + INTERRUPT → PAUSED`,
with `PAUSED + INTERRUPTION_ENDED → PAUSED` and no auto-resume **FACT**.

**Program004R keeps the implemented behaviour and adds `pause_reason`**
(`user`, `focus_lost`, `route_public`, `system`). Reasons: the only transition
that distinguished `interrupted` was auto-resume on focus regain, which is the
behaviour we deliberately refuse; a new state would change the frozen
`SESSION_RUN_STATES` check constraint and every historical run's replay, whereas
a nullable reason column is additive. This divergence from the accepted SDD is
recorded here, and Slice C propagates it to the API, client, journal, UI and
tests so that exactly one model exists.

**DESIGN_DECISION — what is not promised.** If the OS force-stops the app or the
user swipes it away, playback stops. Nothing here promises otherwise. What is
promised is: background playback while the OS permits it, and reliable
reconstruction and resume after relaunch.

## 9. Durable outbox and recovery consistency

### 9.1 Storage

**DESIGN_DECISION.** `sqflite` under `path_provider`'s application-support
directory. Rationale: transactional, crash-consistent, schema-versioned, and
already ubiquitous. A file of JSON lines would need its own atomicity and
migration story; `SharedPreferences` is not transactional and not sized for
this. **An in-memory list must never be the only store** — G5 today.

Schema versioned independently of the server's.

**AMENDED A5 — fixed, measurable quotas.** These are design decisions for this
package, not measurements:

| Setting | Initial value |
|---------|---------------|
| Concurrent active / resumable runs | 1; an existing run is resolved before a new one starts |
| Synced terminal checkpoints retained | ≤ 100 rows **and** ≤ 30 days (this is local pruning, not deletion of server history) |
| Outbox soft limit | 10,000 rows **or** 20 MiB |
| Outbox hard admission limit | 50,000 rows **or** 50 MiB |
| Critical-write reserve | ≥ 1,000 rows **and** ≥ 2 MiB, held for active-run operations, completion and feedback |
| Product audio cache | 150,000,000 bytes soft cap (the inherited 150 MB contract) |

At the soft limit only **reconstructible, non-essential telemetry** is
compacted. Un-ACKed commands, required segment evidence, resolutions,
completions and feedback are never dropped. At the hard admission limit the app
stops starting new runs it could not recover, and syncs or prunes already-ACKed
data first.

Pause and stop always take effect immediately. A failed persist is **reported as
reduced recoverability**, never hidden, and **never** worked around by falling
back to an in-memory list — that would be claiming durability the app does not
have.

### 9.2 What is persisted

**DESIGN_DECISION**, sufficient to resume with no network:

- identity: `session_id`, `plan_hash`, `definition_id`, `resolution_hash`
- `audio_mode` (audible / silent-by-choice / silent-by-degradation) and the
  degradation reason
- `run_state` + `pause_reason`
- last **confirmed** segment boundary and playback position
- `command_sequence`, and stable `command_id` / `event_id` values
- the un-ACKed outbox, with attempt counts and next-retry times
- local file paths and `audio_sha256` per required segment

### 9.3 Transport and application

**DESIGN_DECISION.** At-least-once transport, idempotent application.

- A retry of the same logical command **keeps its original `command_id`**.
  Generating a new one on retry is what turns one command into two.
- The same `command_id` arriving with a **different payload** is a client defect,
  not an ordinary duplicate: the server rejects it as a conflict rather than
  silently accepting either version.
- **Commands** (state-changing, ordered, idempotent by id) and **observational
  events** (append-only, unordered, idempotent by sequence) travel separately
  and are reconciled separately.

### 9.4 Reconciliation rules

**DESIGN_DECISION.** A server response may **never**:

- lower the client's `command_sequence` (the G6 `_adopt` concern);
- discard un-ACKed operations;
- restart a run that has reached a terminal state;
- produce `playing` with no running clock — a state the current
  `_adopt`-then-`setState` path can express today, and which the reconciler must
  make unrepresentable.

Late responses are matched by `command_id` and applied only if they carry
information newer than what the client already has.

### 9.5 Transaction boundaries

**DESIGN_DECISION.** Server: dedupe, state transition and journal append occur
in **one** transaction. The Program004 fix that rolls back a command whose
journal row could not be written is the right shape and is kept.

Client: the checkpoint and outbox write is a single transaction. **Audio
stopping never waits on it** — pause and stop take effect immediately, and the
write follows. A failed persist must be surfaced as reduced recoverability, not
hidden: the app must not claim a recovery guarantee it does not have.

**Recovery of a failed command must restore the state effect and the journal
together.** Appending an event with the right name while the state never changed
produces a journal that reads correctly and describes nothing that happened.

### 9.6 Required failure cases

**PROPOSED_ACCEPTANCE.** Each is a test in Slice D:

1. Server applied the command; the ACK was lost.
2. Client persisted, then crashed before sending.
3. Offline playback, process killed, relaunched.
4. Session completed, feedback entered before any flush succeeded.
5. Out-of-order responses and concurrent duplicates.
6. Guest deletion with requests in flight and an outbox on disk.

### 9.7 Relaunch

**DESIGN_DECISION.** On relaunch the app reads the local plan, resolution,
asset files and checkpoint, and offers resume from the **confirmed boundary**.
A speech segment in progress restarts from the beginning of its utterance —
repeating one sentence beats joining one halfway through.

**Replaying a segment must not double-count completion.** Completion is computed
from distinct covered segments, not from accumulated playback time.

### 9.8 Deletion

**DESIGN_DECISION.** Guest deletion clears that guest's local checkpoint and
outbox. No queued item may resurrect deleted data: entries for a deleted guest
are dropped, not retried, and in-flight requests that land after deletion must
not recreate rows.

The **shared product audio cache is managed separately** and is not cleared: it
holds product-authored content identical for every user and contains nothing
personal — the decision already recorded in Program004 and unchanged here.

## 10. Completion and outcome data

### 10.1 Event semantics

**DESIGN_DECISION.** Distinct, with distinct meanings:

| Event | Means |
|-------|-------|
| `session_started` | The run entered `playing`. |
| **audio output started** | The first sound actually played. New; today unobservable. |
| `segment_completed` | The player reported a segment finished. |
| **silent completion** | Reached the end in silent mode. Not an audible completion. |
| `session_abandoned` | Ended early, deliberately. |
| **feedback saved** | Stored locally and durably. |
| **server acknowledged** | The server confirmed it. |

**DESIGN_DECISION — experiment exposure.** The accepted SDD §5.2 names `ready →
playing` as the exposure boundary for session experiments **FACT**. A
voice-related experiment's exposure fires on **audio output started**, not on
`session_started`: a session that never made a sound was never exposed to a
voice treatment, and counting it would corrupt the comparison.

### 10.2 Offline completion

**DESIGN_DECISION.** A session completed offline proceeds straight to feedback.
Completion and feedback are persisted locally and durably first, shown with a
clear pending-sync state, and synced later.

The user is never blocked waiting for an API. Equally, history must never show a
completion that was silently lost — pending and confirmed are different, and the
UI says which.

### 10.3 What automated tests may claim

**DESIGN_DECISION.** Automated tests prove only what they measure: that a file
was produced, that it decodes, that a callback fired, that state and journal
agree. **Naturalness, pacing and intelligibility require a human listening
record** (§11.3). No automated result may be presented as voice-quality
evidence.

## 11. Acceptance matrix and budgets

### 11.1 Cases

**PROPOSED_ACCEPTANCE** throughout. Evidence tiers: **U** unit · **H** HTTP
integration · **W** Flutter widget · **S** simulator/emulator · **A** Android
device · **I** iOS device · **M** manual listening.

| # | Case | Precondition | Action | Expected sound / state / data | Tier | Pass |
|---|------|--------------|--------|-------------------------------|------|------|
| 1 | Release wiring excludes fake providers | Release-mode adapter set | Inspect injected types | No `Silent*` / `Fake*` audio type present | U,W | Assertion holds |
| 2 | Golden journey, en-US, 5 min | Device with a working voice | Full journey | Audio plays; bells at both ends; feedback and history show it | I,A,M | Heard end to end; history correct |
| 3a | Prepare fails | Backend unreachable at prepare | Start | Never `ready` as audible; degraded mode recorded and explained | W,S | No false ready |
| 3b | No voice available | TTS engine absent | Start | Silent mode offered with reason; `render_failure` recorded | S,A | No false ready |
| 3c | Cache corruption | Tamper a cached file | Prepare | Hash mismatch ⇒ delete + re-synthesise; never played | U,S | Corrupt bytes never reach the player |
| 3d | Disk full | Fill the volume | Prepare | `STORAGE_EXHAUSTED`, user told, no partial file marked ready | S | Degrades, no false ready |
| 4a | Silence floor respected | Overrun < slack | Play | Silence shrinks, never below `min_ms`; UI agrees | U,W | Floors hold |
| 4b | Exactly at budget | Overrun == slack | Play | `absorbed_at_floor`; duration held | U | Boundary exact |
| 4c | Overflow extends | Overrun > slack | Play | Session extends; `extended_by_ms` recorded; remaining/progress/resume agree | U,W,S | Consistent everywhere |
| 5a | Lock screen mid-session | Playing | Lock | Audio continues | I,A | Continues |
| 5b | Next segment after lock | Locked during long silence | Wait past boundary | Next segment plays on time | I,A | Plays |
| 5c | Lock-screen controls | Locked | Pause/play from control centre | State follows; UI agrees on return | I,A | Both directions work |
| 6a | Real focus interruption | Playing | Incoming call | Sound stops first; `paused` + `focus_lost` | I,A | No audio during call |
| 6b | Headphone disconnect | Playing on headphones | Unplug | Sound stops **before** state write; never plays to the room | I,A | Nothing audible |
| 6c | No auto-resume | Paused by interruption | Interruption ends | Stays paused; user resumes | I,A | Silent until user acts |
| 7a | Prepared session offline | `ready`, airplane mode | Play | Full session plays | A,I | Plays offline |
| 7b | Voice offline probe | New utterance, no network | Synthesise | `LOCAL_CONFIRMED` only if it succeeds | A,I | Classification matches observation |
| 8 | Offline kill and relaunch | Playing offline | Kill, relaunch | Resume at confirmed boundary; outbox intact | A,I | Nothing lost |
| 9a | Lost ACK | Server applied, ACK dropped | Retry | Applied once; journal has one row | H,U | No duplicate |
| 9b | Out-of-order responses | Concurrent commands | Shuffle responses | Sequence never decreases; state coherent | U,W | No regression of sequence |
| 9c | Same id, different payload | Conflicting retry | Send | Rejected as conflict, not accepted as duplicate | H | Rejected |
| 10a | Completion/feedback consistency | Offline completion | Sync later | History matches; pending state shown until confirmed | W,H,A | No false completion |
| 10b | Deletion does not resurrect | Outbox non-empty | Delete guest, flush | Nothing recreated | H,U,A | Stays deleted |
| 11 | No regression | — | Full suites | Practices, durations, privacy, migrations, accessibility, CI unchanged | U,H,W | All green |

### 11.2 Device validation rule

**DESIGN_DECISION.** A platform may be called **device-validated** only when at
least one physical device of that platform has completed cases 2, 5, 6, 7 and 8.
Fakes, widget tests and successful release builds do not substitute.

**NOT_RUN.** No physical iOS or Android device is available to this environment.
Every **I** and **A** row above is **NOT_RUN / EXTERNAL_BLOCKED**. All other
engineering and all other tiers proceed regardless; the device rows are marked,
not quietly skipped, and no `device-validated` claim may appear until they run.

### 11.3 Listening record

**DESIGN_DECISION.** A short, dated, human record per voice and locale: pacing,
intelligibility, bell level relative to speech, and whether silences feel
intentional. Stored with the evidence; never generated by a test.

### 11.4 Budgets, fixed now

**DESIGN_DECISION.** Carried over unchanged from the accepted SDD §18: backend
latency budgets; ≤ 6 queries per session create; ≤ 2 per event batch; the 25%
relative regression guard against the Program003 baseline; client audio memory
< 40 MB; cache 150 MB soft cap; backend RSS < 250 MiB.

New thresholds, fixed **before** measurement so that measurement cannot set
them:

| Quantity | Threshold (p95) | n | Environment |
|----------|-----------------|---|-------------|
| Warm full prepare, all files cached + verified | < 800 ms | 30 | mid-tier device, 10-min session |
| Cold full prepare, whole session | < 25 s | 30 | mid-tier device, 20-min session, from plan-in-hand |
| Full-ready → first output, warm player | < 800 ms | 30 | device |
| Full-ready → first output, cold player | < 3,000 ms | 30 | device; **all** required media already verified |
| Pause intent → audio stopped | < 100 ms | 30 | device; callback-measured, hardware latency stated separately |
| Resume → audio | < 250 ms | 30 | device |
| Playback drift at any segment boundary | ≤ 1,000 ms absolute | every boundary, 10-min session | device |
| Relaunch → resumable UI | < 1,500 ms | 30 | device, offline |
| Checkpoint write | < 30 ms, never blocking audio stop | 100 | device |

**AMENDED A1 — there is no first-segment start.** `start` requires the whole
required set verified (§6.1 as amended). Cold full prepare and cold player start
are **two separate measurements** and must not be combined into one number: the
< 25 s figure covers preparing every required file, the < 3,000 ms figure covers
the player's cold start once they are all ready. Progressive-ready and
background synthesis during playback are **out of scope for this package** — one
readiness model, not two.

**DESIGN_DECISION — memory measurement scope.** The 40 MB client audio budget is
**total process resident memory attributable to audio**: decoded buffers, player
native allocations, and cached file handles — *not* Dart heap alone. Measured
with platform tooling (Xcode Instruments / Android Studio Profiler), and the
measurement scope is stated with every figure. A Dart-heap-only number may not
be reported against this budget, and a bounded local test may not be generalised
to "no leaks".

## 12. Compliance, evidence and the release gate

### 12.1 Compliance moves with the capability

**DESIGN_DECISION.** Any slice adding a plugin or a native capability updates,
**in that same slice**: `compliance/third-party-sdks.v1.yaml`, the data-flow
inventory, both platform manifests, and both store privacy mappings.

The packages in §5.2 collect nothing and contact no network service of their
own. **Therefore no subprocessor entry is created, and no microphone, health or
cloud-TTS permission is declared** — inventing one to look thorough is its own
compliance defect. The Android system TTS engine's possible network synthesis
remains disclosed as an OS behaviour, which is already the case.

The local durable store holds guest-scoped session data and so joins the data
inventory and the retention policy, with deletion covered by §9.8.

### 12.2 The release gate, split

**DESIGN_DECISION.** One label per question:

| Axis | Question | Satisfied by |
|------|----------|--------------|
| `toolchain_available` | Can this machine build? | `xcodebuild -version` — **only this** |
| `candidate_build_verified` | Did *this SHA* produce an artefact? | A build whose output is bound to the commit SHA |
| `signing_evidence` | Is there a real signing identity? | Configured credentials |
| `store_identity` | Brand, bundle id, domain | External |
| `device_validation` | §11.2 satisfied per platform | Device runs |

**DESIGN_DECISION.** `candidate_build_verified` must be SHA-bound: neither
`xcodebuild -version` nor the mere existence of a previously-built AAB may
satisfy it. CI already produces genuine release builds for both platforms
**FACT** — that evidence should be consumed rather than re-derived weakly.
Removing signing or identity blockers must not be capable of producing
`STORE_READY`; these axes are independent by construction.

### 12.3 Reporting discipline

**DESIGN_DECISION.** Test counts, CI references, performance environments and
capability statements must match reproducible evidence. Local figures are
labelled local. `push` and `pull_request` CI runs are cited separately, with
their checked-out SHAs (§1.1). A bounded local memory test supports a bounded
local claim and nothing wider.

## 13. Follow-on implementation package

One package, six slices, one execution. **Not** a new plan → review → plan
chain.

### Slice A — Real native adapters and production wiring

- **Files:** `apps/mobile/pubspec.yaml`; `lib/platform/tts_provider_native.dart`,
  `audio_session_native.dart`, `audio_player_native.dart` (new);
  `lib/platform/providers.dart`; `lib/app/app.dart`; bells moved to
  `apps/mobile/assets/audio/bells/`; `scripts/generate_bells.py` output path;
  `compliance/third-party-sdks.v1.yaml`; both manifests as required by the
  plugins.
- **Interfaces:** `TtsProvider` extended (§5.3); `AudioPlayerPort` added;
  `AudioSessionPort` implementation (interface unchanged).
- **Data:** none.
- **Acceptance:** cases 1, 3b; bells bundled and loadable.
- **Rollback (AMENDED A6):** stop admitting new audible runs and offer the
  user-selected silent mode or an explicit unavailable state. Reverting to a
  silent no-op provider that still reports audible completions is **forbidden**.

### Slice B — Prepare, cache, resolved timing, offline, silent mode

- **Files:** `lib/features/session/prepare_controller.dart` (new);
  `lib/core/audio_cache.dart` (new); `lib/core/timeline.dart`;
  `backend/app/domain/timeline/timing.py` (**gains its first caller**);
  `domain/audio/{cache,capability}.py` (**gain callers**);
  `backend/app/api/v1/{routes,schemas}.py`; `persistence/{models,repositories}.py`;
  new migration `0006`; `timing_fixtures.v1.json` (new, shared).
- **Interfaces:** `POST /v1/sessions/{id}/resolution`; prepare response gains
  per-segment readiness.
- **Data:** new `session_resolutions` table; `sessions.resolution_id` nullable
  FK. **Compatibility:** nullable throughout — sessions created before this slice
  have no resolution and replay from the plan, exactly as today. Old clients that
  never POST a resolution keep working. **No migration path requires clearing
  data.**
- **Acceptance:** cases 3a, 3c, 3d, 4a, 4b, 4c, 7a, 7b.
- **Rollback:** stop sending resolutions; the column stays nullable and unused.

### Slice C — Background, focus, route, lock screen

- **Files:** `lib/features/session/playback_service.dart` (new);
  `player_screen.dart`; `playback_controller.dart`;
  `lib/platform/audio_session.dart`; `domain/playback/routing.py` (**gains a
  caller**); `domain/playback/{clock,scheduler}.py` (**gain callers**);
  backend `pause_reason` plumbing; iOS/Android native glue.
- **Interfaces:** `pause_reason` added to the playback command and state
  payloads.
- **Data:** `sessions.pause_reason` nullable; `session_events.detail` carries the
  reason. Nullable, additive, back-compatible.
- **Acceptance:** cases 5a, 5b, 5c, 6a, 6b, 6c.
- **Rollback:** revert to foreground-only playback; `pause_reason` becomes
  unused but harmless.

### Slice D — Durable outbox, checkpoint, reconciliation, kill recovery

- **Files:** `lib/core/durable_store.dart`, `lib/core/outbox.dart` (new);
  `playback_controller.dart`; `player_screen.dart`;
  `domain/playback/failures.py` (**gains a caller**); backend conflict handling
  for same-id-different-payload.
- **Interfaces:** command conflict response; batch ACK semantics.
- **Data:** local sqflite schema v1, versioned independently. Server-side: a
  uniqueness guarantee on `command_id` per session.
- **Acceptance:** cases 8, 9a, 9b, 9c, 10b, and §9.6's six failure cases.
  **The G6 sequence-regression concern gets a failing test first**, then a fix.
- **Rollback (AMENDED A6):** durable storage stays; if it cannot be used, the
  app stops guaranteeing recoverable runs and says so. Degrading to an
  in-memory outbox is **forbidden** — it silently drops the guarantee it was
  introduced to provide.

### Slice E — Completion, feedback, history, exposure, accessibility, compliance

- **Files:** `feedback_screen.dart`; `history_screen.dart`;
  `lib/core/api.dart`; exposure trigger in the player; transcript and silent-mode
  surfaces; `compliance/*`; `app/legal/documents.py` if any statement changes.
- **Interfaces:** pending-sync state exposed to the UI.
- **Data:** locally persisted completion/feedback pending records.
- **Acceptance:** cases 2, 10a; accessibility unchanged; exposure fires on audio
  output started, not on session start.
- **Rollback (AMENDED A6):** data stays and stays readable. Hiding the
  pending-sync state is **forbidden**: a completion shown as confirmed when it
  is not is the defect this slice exists to remove.

### Slice F — Regression, device, performance, evidence, remote closure

- **Files:** `.github/workflows/ci.yml`; `scripts/store_release_gate.py`;
  `backend/scripts/benchmark_paths.py`; `docs/PROGRAM004_STATUS.md`; PR bodies.
- **Work:** full regression; device runs where a device exists; the §11.4
  budgets measured with stated scope; the release gate split per §12.2; G8's
  reporting corrections applied in one pass (PR body 523 → 522; CI citations
  split by event and SHA).
- **Acceptance:** case 11; every number reproducible by a stated command.
- **Rollback:** documentation-only; revertible.

### Merge order (future, not this round)

**DESIGN_DECISION.** Verify and handle PR #3 independently → verify the updated
Program004 candidate → obtain fresh CI on the new candidate → merge per actual
authorisation → read back `main`. **A foundation merge is not Program004 product
DoD.** This round performs none of it.

### Out of scope

Personalization, reminders, paid subscriptions, social, health, camera/mic,
real-time cloud generation, brand finalisation, OCI production deployment.

## 13A. Binding amendments (review of `dc93e84`)

Accepted `PROGRAM004R_SDD_ACCEPTED_WITH_BINDING_AMENDMENTS`. A1 and A5 are
applied in place above (§6.1, §9.1, §11.4, §13 rollbacks). A2, A3, A4, A6, A7
and A8 are normative here and override anything earlier that disagrees.

### A2 — Resolution is established locally; sync is not a playback gate

**DESIGN_DECISION.** The device computes `resolution_hash` under a versioned
canonicalisation, persists the resolution together with the full playback data,
and *then* reaches `ready`. A server ACK is **never** a precondition for an
offline start or resume.

Canonicalisation is pinned so two languages cannot disagree: **UTF-8**, **NFC**,
**fixed field order**, **omit nulls**, **integer milliseconds only** (no
floats), and an explicit `canonicalization_version`. Shared fixtures with
expected hashes are committed and run by both implementations.

The server recomputes the same hash with the same algorithm and validates
**content**, not just sign: segment set identity and order against the frozen
plan, no unknown/duplicate/missing ids, numeric ranges, total duration, silence
floors, and version fields. Non-negativity alone is not validation.

Three states, kept apart: `LOCAL_RESOLVED`, `SERVER_VALIDATED`, `SYNC_CONFLICT`.
Server validation is **not** a claim that the server measured audio or that
anyone heard it.

Audio measurements are recorded as `measurement_source = device_reported`. **No
audio bytes are uploaded** and **no absolute device path is ever sent** to the
backend. Creating a session with no local plan at all is explicitly outside this
package.

A resolution is frozen before playback starts and is never edited in place. If
the runtime must rebuild, playback stops at a legal boundary and a **new
resolution revision** is created, retaining the previous revision, the unmodified
already-played prefix, and the reason.

### A3 — One owner for audio policy

**DESIGN_DECISION.** The stack stays `just_audio` + `audio_service` +
`audio_session` + `flutter_tts` + `sqflite` + `path_provider`, and the version
combination is proven in Slice A by a real resolver, a committed lockfile, a
native build and a smoke test. **Pub scores are not compatibility evidence** and
the SDD's table is provenance for the decision, nothing more. The `sqflite`
version in §5.2 is explicitly re-resolved at pin time — the review could not
independently confirm 2.4.4 versus 2.4.3, and the lockfile is the authority.

A **single `AudioHandler`/runtime** owns UI state, lock screen, focus, route,
media buttons and player callbacks. There is exactly one audio-session owner and
one activation order.

`just_audio` may auto-resume after an interruption by default. This package
constructs the player with **`handleInterruptions: false`** and
**`handleAudioSessionActivation: false`**, taking both over, so that focus or
route loss stops sound immediately and focus regain **always** stays paused.
Only an explicit user action resumes. The common audio-session configuration is
applied after all plugins are loaded, so TTS cannot overwrite the player's
category.

"Stop sound before writing state" is a **program-order guarantee**, not a claim
of zero hardware latency. The callback-to-stop interval is measured; the
hardware interval is stated as unmeasured where it is.

Playback sources are restricted to **verified local file/asset URIs**. Remote
URLs, `LockCachingAudioSource`, proxy `StreamAudioSource` and remote artwork are
not used, and no global cleartext/ATS relaxation is introduced.

TTS waits for a real completion or error signal. A queued request, a `1` return
value, or a filename existing are **not** completion. One serialised queue per
engine, single-flight per key, every async result bound to a
`(request_id, generation)` pair so a cancelled or superseded callback can never
mark anything ready or make sound. Extensions match the real container
(WAV vs CAF). Empty, truncated, unknown-duration or undecodable output is never
`ready`.

### A4 — Long silence is scheduled media, and outputs are immutable

**DESIGN_DECISION.** Required silence is a **bounded local media source the
native pipeline consumes**, not a Dart timer that has to wake up. Auto-advance
across a long silence with the screen locked is verified on both platforms.
Silence is never decoded as one resident PCM block; its size, duration, boundary
error and sample format count against the cache and memory budgets. Internal
chunking must not change a logical segment's identity or double-count it.

Disposing the UI does not end a run the runtime owns, and returning **attaches**
rather than constructing a second player. Nothing keeps the process alive with
meaningless silence after a session ends.

`playing == true`, a `ready` callback, a seek, or a playlist index change are
**not** completion. Auto-skip past a required segment on error must never leave
a run reporting `completed`.

`render_key` indexes inputs; `audio_sha256` identifies immutable bytes. Outputs
are stored at immutable blob paths, a `render_key` maps to one or more verified
outputs, and a resolution binds a **specific output hash** — never an
overwritable slot. Same input producing different bytes is not a bug, but it may
not overwrite a file a live resolution references: either the original bytes are
restored or a new resolution revision is made. An old hash is never used to play
new bytes.

Pinning covers committed assets while `preparing`, and `ready`, `playing`,
`paused`, `interrupted` and any run promised as resumable. LRU may not delete
the next segment because a run is paused or the app restarted; pins survive
relaunch.

The database and the filesystem are not one transaction. The order is
**temporary write → flush and verify → atomic publish → commit the DB
reference**, with orphan and partial-file reconciliation on start-up. The DB
never references an unpublished file. SQLite journal and `synchronous` settings
are recorded, and process-kill durability is tested while power-loss durability
is stated as untested.

### A6 — Identity, transactions and reconciliation

**DESIGN_DECISION.** The runtime is the **single writer** of local sequence and
outbox state; the UI does not open a second write path.

Four identifiers, never conflated: stable `command_id`; `event_id`; a client
`command_sequence`; and a server `revision`. Unordered observational events and
ordered commands do not share a deduplication namespace, and an event's arrival
never consumes a command's sequence or suppresses its state effect.

Server command handling puts **ownership and deletion checks, idempotency
identity, payload digest, state validation, projection update, and the journal
or result record in one transaction**, protected by a real unique constraint and
atomic upsert or row serialisation rather than select-then-insert. The same
command id with the same payload returns the existing result; the same id with a
different payload is an explicit **conflict**. Event batches survive concurrent
duplicates without becoming a 500.

ACK removes only confirmed operations. A server snapshot is separate from an
operation's result: an **older snapshot never rolls back local sequence or
state, never swallows un-ACKed operations, never revives a terminal run, and
never produces `playing` with no running clock.** Adding `max(sequence)` is not
a solution to ordering.

**G6 gets a deterministic reproduction first.** If the original hypothesis
cannot be reproduced it is recorded as **refuted** or **not reproduced** — a red
test is never fabricated — and the new invariants are tested regardless.

Recovery persists **logical playback position and confirmed boundary**, never a
`Stopwatch` value carried across a reboot. A relaunch always presents
`paused`/resumable and never starts making sound on its own; a new monotonic
anchor is established when the user resumes.

Guest deletion covers a local tombstone, in-flight fencing, outbox purge and the
server cascade. A late request may not recreate a deleted guest or session, and
a legitimate deletion is not retried as a transient error. iOS file protection
and Android backup/data-extraction rules are verified so deleted guest data
cannot be restored; the shared product audio cache is classified separately.

### A7 — Completion and exposure semantics

**DESIGN_DECISION.** A voice experiment's exposure fires **once**, and only when
the speech segment corresponding to the assigned treatment has real
**player-output evidence**. An opening bell, silent mode, a synthesis-completed
callback, `session_started`, and player loading/ready are **all excluded**.

Output evidence is named at its platform-observable level — playing state on the
speech source plus position advancing, or a usable native output event — and is
labelled **device-reported delivery evidence**. It is never described as the
user hearing, understanding, or benefiting, and no microphone is added to try to
prove otherwise.

Completion requires valid coverage of **every required logical segment** plus
genuine completion of the final medium. Abandonment is never `completed`.

`completion_ratio` is **non-overlapping covered effective duration ÷ resolved
required duration** — not completed-segment count, which would weight a
one-second bell like an eight-minute silence. A legitimate replay after recovery
is recorded as a replay and does not add to completion or exposure again.

`audio_mode`, `delivery_evidence_version`, `resolution_hash`, pause reason and
pending-sync state are stored separately. Sessions predating this package stay
readable and are marked **legacy / unverified** where audio evidence is absent;
a historical countdown is never promoted to an audible completion.

Feedback is durably saved locally **first**, then shown as saved or
pending-sync. The network never blocks leaving the screen, and a failed disk
write is never reported as saved. Completion, feedback and history agree in
their final projection.

Migrations are additive with explicit versioning and an old-client path. Upgrade
and compatible-read are tested; **no upgrade is achieved by clearing data**, and
downgrade is only exercised against an isolated test database.

### A8 — Module placement, and evidence that means something

**DESIGN_DECISION.** "Seven of ten modules lack a production caller" is a
positioning symptom, not a completion percentage. The acceptance criterion is
**every required user behaviour has a production owner, caller and test** — not
"every Python file is imported".

Logic genuinely executed by Dart/native — clock, scheduler, route policy, device
cache — is **not** force-wired into a Python HTTP path. Each such module is
either kept with a real server-side purpose (resolution validation, replay),
moved to reference/test-support as a cross-language oracle, or deleted. Empty
call sites, decorative entry points and `isImplemented = true` flags are
forbidden ways to pass a gate.

Every slice that changes capability updates the SDK inventory, resolved native
and transitive dependencies, real permissions, `PrivacyInfo`, data flow,
retention and store mappings in the **same** slice. "No analytics" does not imply
"no network capability": each package's enabled paths are checked for this
application. No cloud TTS is delegated, so no subprocessor is invented, and no
microphone, health or commerce capability is added.

## 14. Summary of this round

**FACT.** Baseline re-verified; both PRs genuinely unmerged; `main` unchanged at
`ec82f883`; two CI runs per commit, both green, checking different trees; seven
of ten Program004 backend modules have no production caller; the bells cannot
reach a device; `resolved` is sent unconditionally; completion is a countdown;
pending events are memory-only; the release gate reports toolchain presence as
build success.

**DESIGN_DECISION.** Prepare-time synthesis to verified local files; hybrid
plugin/first-party audio stack with named packages and criteria; `ready` defined
by per-segment verification; two hashes and two offline capabilities kept
distinct; a resolved playback timeline with its own hash giving `resolve_timing`
its first caller; the player as segment-lifecycle authority; `paused` +
`pause_reason` instead of a separate `interrupted` state; a sqflite durable
outbox with reconciliation rules that cannot lower a sequence; exposure on audio
output started.

**PROPOSED_ACCEPTANCE.** Twenty-three cases across seven evidence tiers, with
thresholds fixed before measurement.

**NOT_RUN.** Every device-tier row, for want of a physical device; the G6
sequence-regression hypothesis, which must be reproduced before it is fixed;
package version pinning, which happens in Slice A.

**Disposition: `PROGRAM004R_SDD_ACCEPTED_WITH_BINDING_AMENDMENTS_APPLIED`.**

The amendments are normative from this commit. Implementation proceeds in the
same task, on `program004r/real-audio-durable-playback`, starting at Slice A.
