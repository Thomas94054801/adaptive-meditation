# Software Design Document (SDD)

## Project
Adaptive Meditation — Program003 — Individual-first Store Readiness, Privacy & Identity Foundation

## Document status
This document is the implementation contract for Program003. It is committed
before any Program003 implementation commit, and no implementation commit may
widen the scope defined here.

Predecessors: `SDD_PROGRAM001.md` / `PROGRAM001_STATUS.md`,
`SDD_PROGRAM002.md` / `PROGRAM002_STATUS.md`. Program003 builds on both and
re-opens neither.

---

## 1. Objective

Turn a working adaptive meditation application into a technically and
policy-ready candidate for an **individual developer** launch on the Apple App
Store and Google Play.

Program003 does **not** submit to either store. Submission depends on external
credentials and a final public brand, neither of which exists yet. This program
completes everything that can be completed without them, and names the rest
precisely rather than stopping.

It explicitly does not add: subscriptions, HealthKit, Health Connect, Garmin,
camera, microphone, advertising SDKs, large AI dependencies, or any
company/legal-entity dependency.

---

## 2. Commercialization model

```text
Individual developer → real users → real retention → real subscriptions
    → Incorporation Gate → company migration
```

Company assumptions must not enter source namespaces, the ownership model, the
database, or product metadata. **Brand identity and legal seller identity are
separate concepts** and stay separate, so a later move to a company changes
configuration rather than code.

---

## 3. Guest-first invariant

The core path keeps working with no registration:

```text
install → guest identity → check-in → recommendation → meditation
    → feedback → history
```

No login wall before meditation. Program003 introduces **no mandatory account
creation**. Apple expects apps without significant account-based functionality
to be usable without login; if account creation is ever offered, in-app account
deletion must ship with it.

---

## 4. Guest identity hardening

Program002 stores `guest_id` in app-private preferences. Program003 moves it to
platform-secure storage behind a `SecureIdentityStore` abstraction:

- iOS: Keychain
- Android: Keystore-backed encrypted storage

Requirements:

- locally generated, cryptographically random UUIDv4;
- never derived from IMEI, IDFA, GAID, MAC, hardware or vendor fingerprint;
- survives a normal app restart;
- deleting meditation data rotates the identity;
- uninstall behaviour documented (it differs per platform and must not be
  guessed at);
- **secure-storage failure has explicit handling** — a keychain read can fail on
  a locked device or a restored backup, and silently minting a new identity
  there would strand the user's history under an id nobody holds.

Compliance inventory gains:

```yaml
guest_identity:
  persistent: true
  hardware_derived: false
  advertising_identifier: false
  encrypted_at_rest: true
```

---

## 5. Account model — prepare, do not force

A nullable `user_id` is not a reason to build an authentication system.
Program003 retains or creates the interfaces a future one needs:

```text
AuthProvider
IdentityLinker
GuestMigrationService
```

supporting the conceptual transition `guest_id → authenticated user` with
history preserved. Production Sign in with Apple / Google credentials are not
required; the path may be scaffolded and tested with fakes.

**Missing OAuth credentials must not make Program003 BLOCKED.** Guest mode stays
first-class.

---

## 6. Data ownership model

Three concepts, never one overloaded column:

```text
Principal
├── GuestPrincipal
└── UserPrincipal        (future)
EntitlementPrincipal     (future, store transaction identity)
```

Billing remains Program006. No subscription logic here.

---

## 7. Experiment framework — first consumer

Program002 built deterministic assignment with no consumer. Program003 gives it
exactly one, to prove the wiring end to end.

Experiment: `recommendation_explanation_copy_v1`, variants `concise` /
`contextual`.

It **may** vary explanation wording, presentation ordering, CTA copy and
non-clinical onboarding wording. It **must not** touch safety routing, practice
eligibility, `practice_id`, the duration envelope, data deletion, privacy
choices, subscription state or crisis handling.

Assignment and exposure are persisted **separately**. Being assigned to a
variant is not the same as having seen it, and counting assignment as exposure
would inflate every denominator the experiment is for.

---

## 8. Outcome score — first consumer

`session_outcome_score` is computed and consumed by nothing. Program003 adds one
**non-autonomous** consumer: an offline analytics summary.

```bash
python scripts/outcome_report.py
```

Grouped by practice x goal: session count, completion rate, median primary
outcome, p25/p75, helpfulness distribution.

The pipeline stays:

```text
outcome → evidence → offline analysis → human review → future rule set
```

and never:

```text
outcome → automatic production mutation
```

No dashboard server. A script is the whole requirement.

---

## 9. Minimum sample guard

Below `n = 20` a cell is reported as `INSUFFICIENT_SAMPLE`: raw values are shown,
but practices are **not ranked**.

This is a product analytics guard, not a statistical significance test, and
carries no clinical claim.

---

## 10. Android target requirement

It is September 2026. New Google Play applications require Android 16,
`targetSdkVersion = 36`.

The value must be **pinned explicitly**, not inherited from whatever the Flutter
SDK happens to default to, and a CI check must fail when `targetSdk < 36`.
Inheriting the right answer today is not the same as guaranteeing it tomorrow.

Also verified: `compileSdk` compatibility, `minSdk`, Android Gradle Plugin,
Java/Kotlin compatibility, and release AAB creation via
`flutter build appbundle --release`.

Without signing credentials, produce the maximum unsigned verification possible
and mark signing `EXTERNAL_CREDENTIAL_BLOCKED`. **Android store submission is not
PASS without signing evidence.**

---

## 11. Store identity gate

Bundle and application identifiers are effectively immutable once a production
store identity exists. If the public brand is not approved, **do not invent
one**.

`STORE_IDENTITY_GATE` tracks the unresolved fields: `brand_name`,
`android_application_id`, `ios_bundle_id`, `support_domain`,
`privacy_policy_url`, `support_email`.

Until resolved: `STORE_IDENTITY_GATE = BLOCKED_BRAND_IDENTITY`. This blocks the
creation of immutable store identity **only**, never ordinary engineering.

---

## 12. iOS privacy manifest

Add and validate `PrivacyInfo.xcprivacy`. Audit application code, the Flutter
runtime, every third-party plugin and transitive native SDKs for Apple's
Required Reason APIs, recording API category, originating package, approved
reason and manifest declaration in
`compliance/apple/privacy-manifest-audit.v1.yaml`.

CI validates: the manifest exists, the plist parses, declared APIs carry
reasons, and the inventory agrees with the committed manifest.

**Required reasons must not be fabricated.** Only Apple-approved reason codes
that match actual behaviour.

---

## 13. Third-party SDK privacy audit

`compliance/third-party-sdks.v1.yaml`, one entry per package with native code:
package, version, `ios_native_code`, `android_native_code`, `data_collection`,
`network_access`, `required_reason_api`, `privacy_manifest_present`, `tracking`,
`purpose`.

The goal is a minimal SDK surface. No package may be added for analytics
convenience when first-party telemetry suffices.

Prohibited in V1: Meta SDK, Facebook App Events, advertising attribution SDKs,
behavioural advertising SDKs, device fingerprinting SDKs.

---

## 14. Apple App Privacy source of truth

`compliance/apple/app-privacy.v1.yaml`, derived from and checked against
`compliance/data-inventory.v1.yaml`. Categories must reflect actual code.

Audited at minimum: identifiers, user content, wellness check-ins, session
history, feedback, diagnostics, analytics. For each: collected, linked to
identity, tracking, purpose, shared, retention, deletable.

**No health-data declaration**, because no health data is enabled. Program003
does not enable HealthKit.

---

## 15. Google Play Data Safety source of truth

`compliance/google/data-safety.v1.yaml`, derivable from the same inventory:
data type, collected, shared, ephemeral, required/optional, purpose, encrypted
in transit, user deletion supported.

CI fails if a known data-inventory category has no Data Safety mapping.

---

## 16. Privacy policy

Replace placeholder material with a launch-ready English policy at `/privacy`
describing **actual V1 behaviour only**: that the operator is currently an
individual developer, what is collected (check-in data, session history,
pseudonymous guest identifier, feedback), purpose, retention, deletion, export,
processors, security, international processing, children's policy, contact, and
policy updates.

Forbidden: calling wellness data medical records; claiming HIPAA compliance;
claiming GDPR certification; claiming encryption that does not exist.

---

## 17. Privacy choices page

Public route `/privacy-choices` covering export, deletion, an explanation of the
pseudonymous guest identity, analytics choices where applicable, and future
account handling. Usable without marketing consent. This is the URL Apple's User
Privacy Choices field points at.

---

## 18. Terms of use

A real `/terms`, English-first: wellness product, not medical
diagnosis/treatment, emergency limitation, user responsibilities, acceptable
use, AI limitations if AI content is later enabled, intellectual property,
service availability, termination, and commercial conditions appropriate to an
individual launch.

**No fictitious company names.** The legal operator is a configurable identity,
not a literal in the document.

---

## 19. Wellness disclaimer

One concise product-level disclaimer on a single onboarding/legal surface:
supports mindfulness and wellbeing, is not a medical service, is not emergency
support, and should not delay professional care where required.

Not a warning screen on every path. Constant warnings degrade the product
without adding safety.

---

## 20. Data deletion — UI and server parity

End-to-end, verified as one path:

```text
Flutter → confirmation → DELETE endpoint → database deletion
    → local secure identity reset → new guest identity
```

After deletion the **old guest id must not retrieve history**. Integration test
required.

---

## 21. Data export — UI and server parity

Export reachable from Settings/Privacy as "Export my meditation data". JSON
share/save is acceptable for MVP; no email required.

Export must not be able to reach another guest's data. Authorization boundary
tests required.

---

## 22. Google account-deletion readiness

Program003 provides no account creation, so it documents:

```text
ACCOUNT_CREATION = false
ACCOUNT_DELETION_REQUIREMENT = not yet applicable
GUEST_DATA_DELETION = implemented
```

Account creation must never be introduced without completing account deletion in
the same slice.

---

## 23. Apple account-deletion readiness

Same rule. If Sign in with Apple is ever added, deletion must include Apple token
revocation. **Do not implement Sign in with Apple partially.**

---

## 24. Network security

Production client is HTTPS-only, with no cleartext exception in release and an
environment-controlled API base URL. `localhost` is permitted in debug
configuration only.

Android release: the Network Security Config must not enable global cleartext
traffic. iOS: no broad ATS exceptions.

---

## 25. Secret management

No production secret compiled into the Flutter app. Inherently public mobile
identifiers may exist, but never database credentials, server private keys,
privileged API keys, OCI secrets, App Store private keys or Play service-account
keys.

The credential scanner is extended to Dart, plist, Gradle, xcconfig, JSON and
YAML.

---

## 26. Environment model

Formalize `development` / `staging` / `production`, configuring API base URL,
logging verbosity, analytics endpoint and legal operator metadata.

No separate microservice deployments, and **no business logic duplicated per
flavour** — a flavour that changes behaviour is a second product to test.

---

## 27. Logging privacy

Never log raw meditation free text, complete check-in payloads, the guest UUID,
export payloads, deletion tokens or future auth tokens. Use request ids and
pseudonymous or hashed diagnostic identifiers.

Tests for known logging paths where practical.

---

## 28. Crash and diagnostics policy

No Crashlytics, no Sentry, not automatically. Define the `DiagnosticsProvider`
interface first; V1 default is local/server structured diagnostics.

Any third-party diagnostics vendor requires a data-inventory update, an SDK
audit, an Apple privacy update and a Google Data Safety update **before**
integration.

---

## 29. Store metadata package

```text
store/
├── apple/
│   ├── metadata.en-US.yaml
│   ├── review-notes.md
│   └── privacy-mapping.md
└── google/
    ├── listing.en-US.yaml
    ├── data-safety-mapping.md
    └── review-notes.md
```

A working product description is fine; a final brand must not be invented if
unresolved. No medical claims.

Approved positioning: mindfulness, meditation, stress management, sleep
preparation, focus, emotional reset, self-awareness. Forbidden: treating
anxiety, curing insomnia, diagnosing depression, PTSD treatment, medical stress
detection.

---

## 30. Review demo mode

Reviewers must be able to evaluate core functionality without secret
credentials. Guest mode already makes this true: no review account is needed.

Review notes for both stores document app purpose, the guest entry path, how to
run a meditation, how to view history, how to export and delete data, that there
is no health-device integration in V1, and that there is no subscription in
Program003.

---

## 31. Accessibility baseline

Audit the Program001/002 screens for semantic labels, tap target size, Dynamic
Type / text scaling, screen-reader traversal, contrast and reduced-motion
compatibility.

**No WCAG certification claim.** Automated and widget tests where practical;
unresolved manual checks recorded separately as manual.

---

## 32. iOS release build

```bash
flutter build ios --release --no-codesign
```

Validate: it compiles, `PrivacyInfo.xcprivacy` is embedded, no prohibited
permission strings were added, and there is no HealthKit, microphone, location
or camera entitlement.

Without Apple signing credentials: `IOS_SIGNING = EXTERNAL_CREDENTIAL_BLOCKED`.
That does not fail Program003 engineering completion.

---

## 33. Android release build

```bash
flutter build appbundle --release
```

Verify the AAB and `targetSdk >= 36`, and inspect the **merged** manifest, not
the source manifest — a permission added by a plugin appears only after merge.

Required absent unless justified: `CAMERA`, `RECORD_AUDIO`,
`ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `BODY_SENSORS`,
`ACTIVITY_RECOGNITION`, advertising id permission.

---

## 34. Dependency audit

`flutter pub deps` and the locked Python package set, audited for abandoned
packages, unnecessary native SDKs, trackers and excessive-permission libraries.

No broad upgrades unrelated to Program003 unless required for API 36, the store
build or security.

---

## 35. Subprocessor inventory

`compliance/subprocessors.v1.yaml`, listing **only actual processors**: name,
purpose, data categories, region or scope, whether required for service, privacy
policy.

Hypothetical future OpenAI / Claude / TTS providers are not listed, because they
process nothing today.

---

## 36. Retention model

Explicit, machine-readable retention: guest session history until user deletion
or a stated limit; server logs on a short operational retention; exports
generated on demand and not permanently retained.

No long-term retention invented without a need for it.

---

## 37. Children and age positioning

V1 is not designed or marketed to children. No Kids category, no child
profiling. The launch audience policy is recorded. Targeting minors later
requires its own compliance program.

---

## 38. CI gates

Jobs: `backend`, `flutter`, `arm64-container`, `credential-scan`,
`android-store-readiness`, `ios-store-readiness`, `compliance-consistency`.

Android: `targetSdk >= 36`, release AAB builds, permission audit passes.
iOS, where feasible: release compile succeeds, `PrivacyInfo.xcprivacy` valid,
privacy-manifest audit consistent.

Compliance consistency links data inventory, Apple app privacy, Google Data
Safety, third-party SDK inventory and subprocessors. **A mismatch fails CI** —
four documents that can drift apart are four chances to file a false
declaration.

---

## 39. Store release gate

A script-based `STORE_RELEASE_GATE` over: final brand chosen, bundle id final,
Android applicationId final, privacy policy public, privacy choices public,
support contact configured, Apple privacy mapping complete, Google Data Safety
mapping complete, Apple privacy manifest valid, Android target API >= 36, guest
delete E2E works, guest export works, release builds compile, no prohibited
permissions, no embedded secrets, review instructions ready.

**This gate blocks store submission only. It must never block engineering.**

---

## 40. External credential boundaries

Expected blockers: Apple Developer membership, App Store Connect app record,
Apple distribution certificate, Apple provisioning, Google Play developer
account, Android production signing key, the final public brand, and domain/DNS.

Their absence does not stop Program003. Complete all independent work and return
each as `EXTERNAL_DEPENDENCY_BLOCKED`.

---

## 41. Performance regression

Re-measure domain recommendation, recommendation API and history API. Flag any
unexplained p95 degradation over 25% against the Program002 baseline.

Workstation measurements are never reported as OCI measurements.

Program002 baseline (Apple Silicon workstation):

| Path | p95 |
|------|-----|
| domain recommendation | 0.030 ms |
| recommendation API | 1.070 ms |
| history API (60 sessions) | 7.446 ms |

---

## 42. Resource regression

Re-measure backend container RSS. Program002 observed ~145 MiB. Flag a new
baseline above **250 MiB** without evidence-based justification.

The configured 768 MiB ceiling is a limit, not an expectation.

---

## 43. Experiment evidence test

The same `guest_id + experiment_id` always yields the same variant; different
guest ids distribute across variants; assignment is not exposure; exposure is
logged exactly once per intended exposure event.

---

## 44. Outcome report test

Seed known sessions, run `scripts/outcome_report.py`, verify grouping, `n`,
medians, outcome direction, `INSUFFICIENT_SAMPLE` marking below threshold, and
the absence of any clinical claim.

---

## 45. Deletion integration test

Create a guest with a check-in, recommendation, session, feedback and experiment
assignment. Delete. Verify every associated row is gone or anonymized per the
documented policy, and that the old guest id cannot return the deleted history.

---

## 46. Export isolation test

Guest A and Guest B both hold data. Export A. Assert **zero** B records. This is
a mandatory security test, not a nice-to-have.

---

## 47. Definition of Done

- [ ] Program002 merged and remotely closed
- [ ] Program003 SDD committed before implementation
- [ ] branch starts from validated main
- [ ] guest identity moved to secure storage
- [ ] experiment framework has a real, safe consumer
- [ ] `outcome_score` has an offline evidence consumer
- [ ] minimum sample guard implemented
- [ ] Android target API >= 36 verified
- [ ] Android release AAB builds
- [ ] Android merged permission audit passes
- [ ] iOS release compile succeeds
- [ ] `PrivacyInfo.xcprivacy` exists and validates
- [ ] required-reason API audit exists
- [ ] third-party SDK inventory exists
- [ ] Apple App Privacy mapping exists
- [ ] Google Data Safety mapping exists
- [ ] privacy policy is launch-ready
- [ ] privacy choices surface works
- [ ] terms are launch-ready
- [ ] guest deletion E2E passes
- [ ] guest export UI works
- [ ] export isolation security test passes
- [ ] HTTPS-only production config
- [ ] release apps contain no privileged secret
- [ ] data/compliance mapping consistency check passes
- [ ] store metadata package exists
- [ ] reviewer instructions exist
- [ ] accessibility baseline audited
- [ ] subprocessor inventory exists
- [ ] retention policy exists
- [ ] Store Release Gate implemented
- [ ] backend tests pass
- [ ] Flutter tests pass
- [ ] ARM64 Docker build passes
- [ ] hosted CI green
- [ ] performance regression acceptable
- [ ] memory regression acceptable

These may remain external blockers without failing engineering completion:
Apple signing, App Store submission, Google Play production signing/submission,
final immutable package ids while the brand is unresolved, and domain DNS.

---

## 48. Final disposition

- `PROGRAM003_IMPLEMENTED_CI_GREEN` — engineering complete, store credentials
  and/or brand remain external.
- `PROGRAM003_STORE_READY` — only when every Store Release Gate condition is
  actually satisfied.
- `PROGRAM003_PARTIAL_<reason>` — engineering DoD incomplete.

**Never STORE_READY merely because tests pass.**

---

## 49. Product invariants carried forward

1. wellness, not medical diagnosis or treatment;
2. source-grounded internally, non-sectarian in user-facing language;
3. deterministic core, independent of any external AI;
4. guest-first usability;
5. OCI A1 resource discipline;
6. store-sensitive capabilities deferred or isolated;
7. individual-first commercialization with future company migration;
8. no false test or deployment claims.
