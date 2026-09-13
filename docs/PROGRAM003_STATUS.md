# Program003 — implementation status

Individual-first Store Readiness, Privacy & Identity Foundation.
Contract: `SDD_PROGRAM003.md`.

Every result below was produced by running the stated command. Nothing is marked
PASS on inspection alone, no local result is reported as a hosted or OCI result,
and no store submission is claimed.

## Disposition

**PROGRAM003_IMPLEMENTED_CI_GREEN**

| Field | Value |
|-------|-------|
| Branch | `program003/store-readiness` |
| Pull request | [#3](https://github.com/Thomas94054801/adaptive-meditation/pull/3) |
| Verified SHA | `18ca66d4fbbb21dc21b538e7ad0196085a405663` |
| Workflow run | [34668050269](https://github.com/Thomas94054801/adaptive-meditation/actions/runs/34668050269) |
| Backend (lint, types, tests) | success |
| Android store readiness | success |
| iOS store readiness | success |
| Backend image (linux/arm64) | success |
| Flutter (analyze, tests) | success |
| No committed credential | success |

Not `PROGRAM003_STORE_READY`. The Store Release Gate reports BLOCKED on nine
external conditions — Apple and Google credentials, and a public brand that has
not been chosen. Calling it store-ready because the tests pass is precisely what
section 48 forbids.

## Definition of Done

| Item | Result |
|------|--------|
| Program002 merged and remotely closed | PASS |
| Program003 SDD committed before implementation | PASS — `92a8f19`, alone |
| branch starts from validated main | PASS — from `ec82f88`, CI green at `78d04f18` |
| guest identity moved to secure storage | PASS |
| experiment framework has a real safe consumer | PASS |
| `outcome_score` has an offline evidence consumer | PASS |
| minimum sample guard implemented | PASS — n < 20 marks `INSUFFICIENT_SAMPLE` |
| Android target API >= 36 verified | PASS — pinned literal, merged manifest confirms |
| Android release AAB builds | PASS — 50.6 MB |
| Android merged permission audit passes | PASS — INTERNET only |
| iOS release compile succeeds | PASS — on CI (macOS runner), run 34668050269 |
| `PrivacyInfo.xcprivacy` exists and validates | PASS |
| required-reason API audit exists | PASS |
| third-party SDK inventory exists | PASS |
| Apple App Privacy mapping exists | PASS |
| Google Data Safety mapping exists | PASS |
| privacy policy is launch-ready | PASS |
| privacy choices surface works | PASS — `/privacy-choices` |
| terms are launch-ready | PASS |
| guest deletion E2E passes | PASS — all seven tables verified empty |
| guest export UI works | PASS |
| export isolation security test passes | PASS |
| HTTPS-only production config | PASS |
| release apps contain no privileged secret | PASS |
| data/compliance mapping consistency check passes | PASS |
| store metadata package exists | PASS |
| reviewer instructions exist | PASS |
| accessibility baseline audited | PASS — automated floor; manual checks listed below |
| subprocessor inventory exists | PASS |
| retention policy exists | PASS |
| Store Release Gate implemented | PASS |
| backend tests pass | PASS — 330 |
| Flutter tests pass | PASS — 70 |
| ARM64 Docker build passes | PASS |
| hosted CI green | PASS — all six jobs, run 34668050269 |
| performance regression acceptable | PASS with two explained flags |
| memory regression acceptable | PASS — 146.2 MiB against a 250 MiB flag |

## Store Release Gate

`python scripts/store_release_gate.py` → **BLOCKED** (exit code 2).

Exit 2 means every engineering condition passed and only external dependencies
remain. Exit 1 would mean an engineering condition failed. The gate blocks store
submission and nothing else.

| Condition | Result |
|-----------|--------|
| Android target API >= 36 and permissions | PASS |
| compliance mappings consistent | PASS |
| Apple privacy manifest valid | PASS |
| Apple privacy mapping present | PASS |
| Google Data Safety mapping present | PASS |
| third-party SDK inventory present | PASS |
| subprocessor inventory present | PASS |
| retention policy present | PASS |
| Apple review notes ready | PASS |
| Google review notes ready | PASS |
| Apple listing metadata ready | PASS |
| Google listing metadata ready | PASS |
| release config is HTTPS-only | PASS |
| no prohibited iOS permission strings | PASS |
| no embedded secrets | PASS |
| Android release AAB builds | PASS |
| iOS release compile | BLOCKED locally, PASS on CI |
| Android production signing key | BLOCKED — external |
| Apple distribution certificate | BLOCKED — external |
| brand_name final | BLOCKED — external |
| ios_bundle_id final | BLOCKED — external |
| android_application_id final | BLOCKED — external |
| support_domain final | BLOCKED — external |
| privacy_policy_url final | BLOCKED — external |
| support_email final | BLOCKED — external |

## External dependency blockers

None of these is an engineering failure, and none of them stopped the work.

| Blocker | Kind | Effect |
|---------|------|--------|
| Full Xcode not installed on this machine | toolchain | `flutter build ios --release --no-codesign` could not be run locally. CI runs it on a macOS runner and it passed, so this blocked nothing. |
| Apple Developer membership / distribution certificate / provisioning | credential | No signed archive, no App Store Connect record |
| Google Play developer account and upload keystore | credential | AAB builds unsigned; no production upload |
| Final public brand | product decision | Bundle id, applicationId, domain and support email all derive from it |
| Support domain / DNS | product decision | Privacy policy and support URLs cannot be published |

## Guest identity

Moved from app-private preferences to platform-secure storage.

| Property | Value |
|----------|-------|
| Storage | Keychain (iOS), Keystore-backed AES-GCM (Android) |
| Interface | `SecureIdentityStore` |
| Identifier | RFC 4122 v4 UUID from `Random.secure()` |
| Device-derived | no — not IMEI, IDFA, GAID, MAC, hardware or vendor fingerprint |
| Survives restart | yes |
| Backup / device transfer | excluded on both platforms |
| Rotates on deletion | yes, old value removed before a new one is written |
| Failure handling | explicit, and the three cases are distinguished |

Secure storage can fail, and the failures are not equivalent:

- **device locked** — transient, so `resolve()` rethrows. Minting a new id there
  would strand the existing history under an identifier nobody holds.
- **item unavailable / store unavailable** — permanent, so an *ephemeral*
  identity is returned and reported, letting the UI say the session will not
  persist rather than implying durability it does not have.

`shared_preferences` was removed entirely. That also removed the app's only
UserDefaults usage, which is why the Apple privacy manifest declares no Required
Reason API at all.

## Verification commands and results

Backend, from `backend/`:

| Command | Result |
|---------|--------|
| `ruff check .` | All checks passed |
| `ruff format --check .` | all files already formatted |
| `mypy` (strict) | Success: no issues found in 47 source files |
| `pytest` (PostgreSQL 16.15) | **330 passed** |
| `alembic upgrade head` / `downgrade 0002` / `upgrade head` | applied and reversed, no pending diff |
| `python scripts/export_openapi.py --check` | matches the implementation |
| `python scripts/outcome_report.py` | runs, reports, changes nothing |

Client, from `apps/mobile/`:

| Command | Result |
|---------|--------|
| `flutter analyze` | No issues found |
| `flutter test` | **70 passed** |
| `flutter build appbundle --release` | **succeeded, 50.6 MB** |
| `flutter build ios --release --no-codesign` | **not run locally** (full Xcode absent); **succeeded on CI** |

Gates, from the repository root:

| Command | Result |
|---------|--------|
| `python scripts/check_android_store_readiness.py --merged-manifest …` | PASS |
| `python scripts/check_compliance_consistency.py` | PASS |
| `python scripts/check_committed_secrets.py` | clean, 178 tracked files |
| `python scripts/store_release_gate.py` | BLOCKED (exit 2), engineering conditions all PASS |

Image, from the repository root:

| Command | Result |
|---------|--------|
| `docker build -f backend/Dockerfile .` | succeeded, `linux/arm64`, 73.1 MB |
| container `/healthz` with no database and no AI key | 200, 7 practices, engine 2 / rules 2 / knowledge 2 |
| container `/v1/recommendations` | 200, `mindful_walking` |
| `docker exec … id` | `uid=999(app)` — non-root |

## Android

| Property | Value |
|----------|-------|
| `targetSdk` | **36**, pinned as a literal |
| `compileSdk` | 36, pinned |
| `minSdk` | 24, pinned |
| Java / Kotlin | 17 |
| Release AAB | built, 50.6 MB |
| Requested permissions (merged release manifest) | `android.permission.INTERNET` |
| Toolchain-generated | `<applicationId>.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` (AndroidX, signature-level, app-scoped) |
| Cleartext traffic (release) | disabled, no exception |
| Backup / device transfer | excluded |
| Signing | **EXTERNAL_CREDENTIAL_BLOCKED** — no upload keystore |

The permission list is from the **merged** manifest produced by a real release
build, not the source manifest. The source manifest cannot see a permission
contributed by a plugin, and the gate found one on its first run.

## iOS

| Property | Value |
|----------|-------|
| `PrivacyInfo.xcprivacy` | present, parses, registered in the Xcode project's Resources phase |
| Tracking | false; no tracking domains |
| Collected data types | `NSPrivacyCollectedDataTypeUserID`, `NSPrivacyCollectedDataTypeOtherDataTypes` |
| Health and Fitness declared | **no** — HealthKit is not enabled |
| Required Reason APIs (app level) | **none** |
| Prohibited permission strings in `Info.plist` | none |
| Release compile | **PASS on CI** — `flutter build ios --release --no-codesign` on a macOS runner |
| Manifest embedded in the built `.app` | **verified on CI** — the step fails if it is absent |
| Signing | **EXTERNAL_CREDENTIAL_BLOCKED** |

The app-level Required Reason API array is empty because it is accurate.
Keychain is not a Required Reason API, and `shared_preferences`, whose
UserDefaults access would have needed CA92.1, was removed in this program.
Inventing a reason code would have been worse than declaring none.

## Performance

**MEASUREMENT ENVIRONMENT: Apple Silicon (arm64) macOS workstation, Python
3.12.14, local PostgreSQL 16.15. NOT AN OCI A1 MEASUREMENT.**

| Path | p50 | p95 | Program002 p95 | Delta | Target |
|------|-----|-----|----------------|-------|--------|
| domain recommendation | 0.028 ms | 0.030 ms | 0.030 ms | +0.7% | < 20 ms |
| recommendation API (no guest) | 1.153 ms | 1.365 ms | 1.070 ms | **+27.6%** | < 150 ms |
| recommendation API (with guest) | 1.912 ms | 2.318 ms | 1.070 ms | **+116.6%** | < 150 ms |
| history API (60 sessions) | 7.229 ms | 7.920 ms | 7.446 ms | +6.4% | < 300 ms |

Two paths exceed the 25% relative guard. Both are **explained**, which is the
distinction section 41 draws:

- **with guest, +116.6%** — the experiment assignment must be persisted, so a
  path that previously touched no database now performs one lookup. Steady state
  is a single SELECT; the guest profile is created only on the first assignment.
- **no guest, +27.6%** — stable across three runs at 1.34–1.39 ms, so it is real
  rather than variance. The response model gained a nested optional
  `explanation_variant`. Both are contract requirements.

One unexplained regression was found and fixed rather than reported: adding
`DbSessionDep` to the recommendation route acquired a pooled connection on
**every** call, including the ones with no guest identity, taking p95 to 1.789 ms
(+67%). The route now takes the database object and opens a session only when
there is something to write — which is also what keeps it answerable with the
database down.

Absolute headroom against the targets is 65× on the slowest flagged path.

## Memory

**MEASUREMENT ENVIRONMENT: Colima VM on the same workstation. ACTUAL OCI
DEPLOYMENT: NOT MEASURED.**

| Quantity | Program002 | Program003 | Threshold |
|----------|-----------|------------|-----------|
| Container RSS | 145.0 MiB | **146.2 MiB** | flag above 250 MiB |
| Image size | 72.9 MB | 73.1 MB | — |
| Configured ceiling | 768 MiB | 768 MiB | — |

+1.2 MiB. No regression.

## Known gaps

1. **No OCI deployment.** Every latency and memory figure here is from this
   workstation. Nothing has been deployed and no OCI credential is configured.
2. **iOS release build is CI evidence, not local evidence.** Full Xcode is not
   installed on this machine. The `ios-store-readiness` job built the release
   app on a macOS runner and verified `PrivacyInfo.xcprivacy` is inside the
   resulting bundle, so the result is real - it was simply not produced here.
3. **Accessibility is an automated floor, not a conformance claim.** Tap target
   size, contrast, labelling and 2x Dynamic Type are asserted. Screen-reader
   traversal order, real VoiceOver and TalkBack behaviour, and reduced-motion
   handling still need a person on a device — recorded as manual checks below.
4. **Account model is interfaces only.** `AuthProvider`, `IdentityLinker` and
   `GuestMigrationService` exist as boundaries with no implementation, by
   design. Guest mode stays first-class and nothing is blocked on OAuth
   credentials.
5. **The test suite still cannot run twice concurrently on one database**, and
   it bit again during this program: a benchmark sharing `adaptive_test` with a
   running suite produced four spurious failures and nine errors. Benchmarks now
   use a separate `adaptive_bench` database, but the underlying per-session
   drop-and-recreate fixture is unchanged and should get a per-run schema name.

## Manual accessibility checks still outstanding

Not claimed as done, because they cannot be automated:

- screen-reader traversal order on a real device (VoiceOver, TalkBack)
- focus behaviour when the session player advances a stage
- reduced-motion preference handling for the progress indicator
- colour contrast under the platform's high-contrast settings
- external keyboard and switch-control navigation
