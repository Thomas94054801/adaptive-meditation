# PROGRAM005 — Personalization

## Guest-first adaptive presentation, familiarity and local reminders

Status: SDD, ready for review. No implementation in this commit.

Baseline: `PROGRAM005_BASE = 367736a2d4269ac1a951d82e5fb0233d1d59238f`
(verified `origin/main`; final Program004R `main` push CI `34760778807`
SUCCESS; open PRs 0; worktree clean).

Style follows the Program004R SDDs: **FACT** is something read in the
repository at the baseline, with a file reference; **DECISION** is frozen
here and is not an implementation-time option.

## 1. Product objective

The product should feel increasingly adapted to the individual across repeated
sessions while practice selection stays deterministic, content stays
source-grounded, the app stays guest-first and account-free, and the backend
stays a FastAPI monolith on one OCI A1 instance.

Three bounded capabilities, nothing else:

```text
A. familiarity-aware presentation   (core)
B. explicit personalization preference
C. optional local practice reminder
```

Each must be visible to a person using the app. A returning guest hears a
different opening and can read why; a preference switch changes what they
hear next; a reminder arrives at the time they chose. Dormant interfaces are
not personalization.

## 2. Frozen boundaries

### 2.1 Practice-selection authority

**FACT.** `create_session` (`backend/app/api/v1/routes.py:241`) re-derives the
recommendation from the stored check-in and rejects a submitted one that
differs (409 `recommendation_mismatch`). `RecommendationEngine` is pure: no
database, no provider.

**DECISION.** Nothing in Program005 — familiarity, preference, AI output,
reminder state, outcome evidence — is an input to `RecommendationEngine`,
`build_plan`'s allocation, `select_duration`, `select_guidance_density`, the
contraindication checks or the protocol identity. `practice_id`,
`duration_minutes`, `guidance_density`, stage count and stage order are
computed before personalization runs and are compared after it (§5.5).
The state-space and v1 replay suites stay as they are; the expected matrix
is not regenerated.

### 2.2 Outcome score

**DECISION.** `session_feedback.outcome_score` remains a product optimisation
metric. Program005 reads no feedback row and no outcome field on any request
path. Familiarity counts completed sessions (§4.2); it never reads what the
person reported about them. There is no online learning loop of any kind: no
model, no training, no reinforcement, no embedding, no vector store.

### 2.3 AI

**FACT.** `AIProvider`, `PersonalizationRequest`, `PersonalizationResult`
(`backend/app/ai/providers/base.py`), `apply_personalization`
(`backend/app/ai/guard.py:43`) and `build_ai_provider`
(`backend/app/ai/providers/registry.py:20`) exist. `build_ai_provider` has no
caller outside `backend/tests/test_ai_boundary.py`; `main.py` never builds a
provider. The path is designed and unreachable.

**DECISION.** Program005 makes that path reachable with the null provider only
(§6). No OpenAI, Anthropic, Gemini or local-model adapter, no GPU, no RAG, no
prompt store, no agent framework. `AI_PROVIDER=null` with no key is the
production configuration and every acceptance case runs under it.

### 2.4 Out of scope

Commerce (Program006/007): entitlement, paywall, trial, StoreKit, Play
Billing, accounts, brand, submission. Health (Program008): HealthKit, Health
Connect, wearables, heart rate, sleep, camera, microphone, biometrics. Also:
push infrastructure, device tokens, campaigns, remote schedulers,
notification analytics, cloud preference sync, profiles, quizzes,
demographics.

## 3. Pipeline

```text
check-in
  ↓ deterministic recommendation            (unchanged)
  ↓ canonical protocol                      (unchanged)
  ↓ familiarity → presentation variant      (new, §4–§5)
  ↓ AI presentation rewrite IF provider     (new caller, §6; null in 005)
  ↓ envelope + wording guard                (extended, §6.3)
  ↓ frozen SessionDefinition + provenance   (§7)
  ↓ plan_session / build_plan               (unchanged)
  ↓ Program004R prepare / resolution / playback (unchanged)
```

All of it runs inside `create_session`, in the same database transaction,
before the `sessions` row is written. With the null provider the added cost is
one bounded query (§4.3) and no I/O.

## 4. Slice A — familiarity

### 4.1 Tiers

**DECISION 1.** Two tiers, `new` and `returning`. Inspection gives no reason
for a third: every protocol has exactly one orientation stage (§5.1), so there
is exactly one thing to vary, and it either has been heard before or has not.

### 4.2 Rule

**DECISION 2.** `personalization_policy_version = "1"`:

```text
evidence_count = completed sessions of this guest whose practice_id equals
                 the recommended practice_id, capped at EVIDENCE_CAP = 100
new        : evidence_count == 0
returning  : evidence_count >= 1
```

Threshold 1, not 2: the criterion is "has heard this orientation before", not
"is experienced". "Completed" is `sessions.status = 'completed'`, which both
the feedback path (`SessionRepository.finish`) and the playback `complete`
command set; abandoned sessions do not count. The practice is the
version-independent `practice_id`, so a session completed under knowledge v1
counts toward the same practice under v2.

No guest identity (`OptionalGuestDep` is `None` and the check-in has no
guest) → `new`, `evidence_count = 0`, reason `no_history_available`.

Familiarity depends on that one count and nothing else. It does not read
check-in values, feedback, notes, outcome fields, timestamps beyond ordering,
experiment arms or device facts. It infers no trait, no diagnosis and no
protected attribute, and the SDD forbids adding an input to it without a
policy-version bump.

### 4.3 Query

**FACT.** `sessions` has no `practice_id` column; the practice is
`recommendation->>'practice_id'` (JSONB on PostgreSQL, `models.py:25`). The
only relevant index is `ix_sessions_guest_id`. A guest's rows are bounded by
one person's own sessions — the same bound the export relies on.

**DECISION 3.** One statement, no new index, no new table, no cache:

```sql
SELECT count(*) FROM (
  SELECT 1 FROM sessions
   WHERE guest_id = :guest_id
     AND status = 'completed'
     AND recommendation->>'practice_id' = :practice_id
   LIMIT 100
) AS bounded;
```

Cost is an index range scan over this guest's rows with early exit at 100
completed matches. A composite index would not change the row count the scan
touches at the volumes one person produces, so none is added. The result is
`evidence_count` with `evidence_capped = (count == 100)`; the tier is the same
either side of the cap. The count is `SessionRepository.completed_count(...)`
and the SDD-listed benchmark path in §11 measures exactly it.

## 5. Slice A — presentation variants

### 5.1 What varies

**FACT.** Every v2 protocol (`knowledge/protocols.v2.yaml`) begins with a
stage `arrive` whose intent is posture or contact and whose prompt is 13–24
words. Later stages carry the practice itself.

**DECISION 5.** Under policy 1 only the first stage's `prompt_template` may
vary, and only between two variants: `canonical` (the existing text) and
`returning`. Practice family, duration, stage count, stage order, stage
intents, `silence_after_seconds`, `min_silence_seconds`, bells and safety
constraints are identical across variants by construction, because the variant
substitutes one string in one stage and nothing else.

Speech length may change; `build_plan`'s speech-then-silence split within the
stage absorbs it and Program004R resolution absorbs the real synthesised
duration. No timing code changes.

### 5.2 Representation

**DECISION 4.** One optional field on `ProtocolStage`
(`backend/app/domain/practice/models.py:109`, `extra="forbid"`):

```yaml
- id: arrive
  prompt_template: "…canonical…"
  returning_prompt_template: "…returning…"   # optional; policy 1: first stage only
```

authored in `knowledge/protocols.v2.yaml` — the live authoring surface; v1
stays frozen. Catalog validation (`catalog.py`, at load): the field is allowed
on the first stage only; it passes `assert_public_language`; it is 1–600
characters; its `${…}` placeholder set equals the canonical stage's; and its
word count is ≤ the canonical word count, so a returning opening can only be
shorter. Seven strings are added, one per practice; no protocol is duplicated.

A separate variants file was considered and rejected: it needs its own loader
and a cross-reference check that the inline field makes unnecessary.

### 5.3 Frozen content (policy 1)

Placeholders and word bounds as in §5.2. Canonical text is unchanged.

| practice | returning `arrive` |
|---|---|
| breath_awareness | Welcome back. Settle in for ${duration_minutes} minutes and let the shoulders drop. |
| body_awareness | Welcome back. For ${duration_minutes} minutes, let attention come down into the body and find where it meets the floor or chair. |
| feeling_tone | Welcome back. Take ${duration_minutes} minutes here, alert and comfortable, and let the breath settle. |
| thought_observation | Welcome back. Settle for ${duration_minutes} minutes and let the breath find its rhythm. |
| kindness | Welcome back. Take ${duration_minutes} minutes and let the face and shoulders soften. |
| open_awareness | Welcome back. Sit upright for ${duration_minutes} minutes, eyes soft. |
| mindful_walking | Welcome back. Stand for a moment, feel your feet on the ground, and take your ${duration_minutes} minutes. |

Canonical meaning is unchanged: each returning line keeps the posture/contact
instruction and drops the explanation a person has already heard.

### 5.4 Definition

**FACT.** `SessionDefinition` (`timeline/definition.py`) is content-addressed;
`DEFINITION_SCHEMA_VERSION = 1` (`definition.py:21`). No test and no fixture
pins a literal `definition_id` or `plan_hash` (`test_timeline.py` compares
structurally; `timing_fixtures.v1.json` carries `plan_hash` only as an input
string).

**DECISION.** `DEFINITION_SCHEMA_VERSION` becomes 2 with one new field,
`presentation_variant` (`canonical` | `returning`), in `as_dict` and therefore
in the hash. `from_dict` reads a schema-1 document with the variant defaulting
to `canonical`. Every definition frozen before Program005 keeps its id and stays
readable; new sessions freeze schema-2 definitions (seven canonical, seven
returning, content-addressed and shared). `source` stays `authored` for both
variants and becomes `generated` only for accepted provider wording (§6.4).

### 5.5 Invariant check

**DECISION.** After personalization and before persisting, `create_session`
asserts, against the canonical definition for the same recommendation:
equal `practice_id`, `protocol_id`, `duration_minutes`, `guidance_density`,
stage count, and per stage equal `stage_id`, `intent`,
`silence_after_seconds`, `min_silence_seconds`. A mismatch is a server
defect (500, logged without prompt text), never a silently different
session. This is what PERS-03/04/05 execute.

## 6. Slice B — the AI path becomes reachable

### 6.1 Wiring

**DECISION 7.** `main.py` builds `app.state.ai_provider =
build_ai_provider(settings)`; `deps.py` exposes `AIProviderDep`. The call
sits in `create_session` between variant selection and definition freezing
(§3), inside the request. Session start never waits on it: by the time
prepare runs the definition is frozen. With the null provider the call is a
pure function returning the input.

### 6.2 Request contents

**DECISION.** `PersonalizationRequest` gains `presentation_variant`. It carries
the envelope (`practice_id`, `duration_minutes`, `guidance_density`), the
variant's stage prompt templates with placeholders intact, and the variant
name. It never carries guest id, session id, check-in values, history,
experiment arm, feedback, free text or device facts, and — as for TTS — a
check over the serialised request enforces the forbidden-key list in tests.
No user free text reaches a model, so `NoopSafetyRouter` is not on this path
and no classification claim is made.

### 6.3 Guard

**FACT.** `check_envelope` (`guard.py:27`) compares `practice_id`,
`duration_minutes`, `guidance_density` and stage count.

**DECISION.** The guard adds wording admissibility, evaluated per stage after
the envelope: `placeholders` (the `${…}` set must equal the request's),
`empty`, `length` (>600), `public_language` (`assert_public_language`). Any
violation keeps the request's wording; `GuardOutcome.violations` names the
first field that failed. `strict=True` still raises for the provider suite.

### 6.4 Failure behaviour

**DECISION 8.** Exactly one attempt per session, no retry. Any of: provider
absent (`null`), preference off, exception, timeout raised by the provider,
malformed result, envelope or wording violation → the deterministic variant
wording is frozen and `fallback_reason` records one of:

```text
provider_absent | adaptive_wording_disabled | provider_error |
provider_timeout | malformed_output | envelope_violation | wording_rejected
```

Session creation never fails because personalization failed. An accepted
rewrite is frozen as a `generated` definition — one row per personalized
session, the same growth as the `sessions` row itself. Program005 ships no
provider that can produce one.

### 6.5 Preference transport

**DECISION.** `SessionCreateRequest` gains `adaptive_wording: bool | None`
(absent → `true`, matching the default preference so an older client is
unchanged). `false` selects the canonical variant and skips the provider
call; the applied value is frozen in provenance (§7). No backend preference
table: the value is per request and per session.

## 7. Provenance and immutability

**DECISION 6 / 16.** One additive nullable column, migration 0008:
`sessions.personalization JSONB NULL`, written once at create, never
updated. Pre-Program005 rows read as `null`, which the client renders as "not
personalized". Cascade deletion covers it with no new statement.

```json
{
  "schema_version": 1,
  "personalization_policy_version": "1",
  "familiarity_tier": "returning",
  "evidence_count": 3,
  "evidence_capped": false,
  "presentation_variant": "returning",
  "adaptive_wording_enabled": true,
  "personalized": true,
  "provider_id": "null",
  "ai_attempted": false,
  "ai_accepted": false,
  "fallback_reason": "provider_absent",
  "reason": "returning_to_this_practice"
}
```

`personalized` is `presentation_variant != "canonical" or ai_accepted`.
`reason` is one of `returning_to_this_practice`,
`first_time_with_this_practice`, `adaptive_wording_off`,
`no_history_available`; the client owns the display strings. No outcome
field, no score, no model reasoning.

The object is returned in `SessionResponse.personalization` (create and `GET
/v1/sessions/{id}`) and exported as `sessions[].personalization`. Together
with the content-addressed definition it answers what was personalized, why,
under which policy, whether AI ran and whether it passed. A session created
today does not change when history grows, the preference flips, a provider
appears, or the knowledge file is edited: the words are in the definition and
the facts are in the column (PERS-07/08).

## 8. Slice B — preference

**DECISION 9.** One presentation preference, `adaptive_wording_enabled`,
default `true`, label "Adapt the wording to my history". One reminder group
(§9). Nothing else; no profile.

**FACT.** `DurableStore` is sqflite schema 2 (`durable_store.dart:173`) with
`checkpoints`, `outbox`, `deleted_guests`, `feedback`. `SecureStorageProvider`
holds one value, the guest id, and on iOS is keychain-backed, which survives
uninstall.

**DECISION 10.** Preferences live in `DurableStore`, schema 3, one additive
migration (`migrate` gated on `from < 3 && to >= 3`):

```sql
CREATE TABLE preferences (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at_ms INTEGER NOT NULL
);
```

Keys: `adaptive_wording_enabled`, `reminder_enabled`, `reminder_hour`,
`reminder_minute`. Not the secure store: a preference must not outlive an
uninstall, and the compliance note describing that store as "one value" stays
true. `forgetGuest` gains `DELETE FROM preferences`.

Surface: one new screen, `features/settings/settings_screen.dart`, reached
from the history screen's app bar beside export/delete. The player shows one
line under the title when `personalized` is true (e.g. "Wording adapted:
returning to this practice"), and the transcript sheet shows variant, policy
version and whether AI was used. That is the whole UI.

## 9. Slice C — local reminder

### 9.1 Mechanism

**FACT.** `NotificationProvider` (`providers.dart:163`) exposes `isSupported`
and `requestPermission()`; the shipped implementation never touches a platform
API. No dependency in `pubspec.yaml` can schedule a notification.

**DECISION 11.** One plugin, `flutter_local_notifications`, latest stable
major at implementation time, exact version pinned by the lockfile and recorded
in the SDK inventory. A first-party Android implementation (AlarmManager, boot
receiver, channel, permission-result plumbing, Doze behaviour) is the class of
code Program004R declined for the foreground service, for the same reason: it
fails silently and only a device shows it. pub.dev was not reachable from this
task, so no version is asserted here.

The plugin's scheduling API takes a `TZDateTime` from the pure-Dart `timezone`
package it already depends on. Importing it requires declaring it
(`depend_on_referenced_packages`, in `flutter_lints`). Budget statement, so
the reviewer counts it the way they wish: one new native SDK; two new pubspec
lines, the second pure Dart and already in the lockfile's closure, listed
under `dart_only_dependencies`. If the reviewer holds the count at one
pubspec line, the alternative is a first-party native implementation and this
slice grows by the Kotlin above.

**DECISION.** Schedule = a rolling window of the next 14 daily occurrences as
one-shot notifications at fixed ids 1000–1013, refreshed on every app resume
and on every preference change (cancel the window, re-add). Instants are
computed from Dart local `DateTime`, which follows the device zone and DST,
and passed as UTC `TZDateTime`; no time-zone name lookup and no second
plugin. Android schedule mode is inexact-allow-while-idle; no exact-alarm
permission is used or declared. A device unopened for 14 days stops reminding
until the next open — intended, not a defect. Weekday selection is not in
policy 1; if added later it is a filter over the same window.

### 9.2 Interface

**DECISION.** The smallest extension, no second abstraction:

```dart
enum ReminderPermission { granted, denied, undetermined, unsupported }
class ReminderTime { final int hour; final int minute; }
abstract interface class NotificationProvider {
  bool get isSupported;
  Future<ReminderPermission> permissionState();
  Future<bool> requestPermission();
  Future<void> scheduleReminder(ReminderTime time);  // replaces any existing
  Future<void> cancelReminder();
}
```

`DisabledNotificationProvider` stays inert (`unsupported`, `false`, no-ops)
and remains what tests and the release-wiring audit see unless
`LocalNotificationProvider` is injected in `bootstrap.dart`. The interface has
no text parameter: the copy is a constant inside the provider (§9.4), so
state cannot reach a notification by construction.

### 9.3 Permission

**DECISION 12.** Requested only inside the settings toggle's own flow:

```text
user turns "Daily reminder" on
  → sheet: "A local reminder at the time you choose. It stays on this
     device. You can turn it off any time."  [Not now] [Continue]
  → Continue → requestPermission()
  → granted: persist enabled + time, schedule window
  → denied : persist disabled, show "Notifications are off for this app.
             You can allow them in system settings."
```

Never on first launch, onboarding, opening settings, or upgrade. Denial is a
normal state. If the OS permission is later revoked, the preference stays as
set, the settings screen shows the system-settings hint, and nothing prompts.
On iOS `requestAuthorization` with alert+sound; on Android 13+ the runtime
`POST_NOTIFICATIONS` request; below 13 `granted`.

### 9.4 Copy

**DECISION.** Constants in `platform/reminder_copy.dart`:

```text
title: Time for a mindful pause
body : A few quiet minutes are waiting.
```

No state, score, goal, practice name, streak or number. Not localised in
Program005 (English-first); a localisation key is the later mechanism, not
generated text, and never a model output.

### 9.5 Persistence, reset, deletion

**DECISION 13.** The preference (`reminder_enabled`, hour, minute) is the
record; the OS pending-request list is derived state, rebuilt on resume.

**FACT.** `DurableStore.forgetGuest` (`durable_store.dart:549`) clears
outbox, checkpoints and feedback and writes the tombstone, but
`showDeleteDataDialog` (`delete_data_dialog.dart:48-51`) calls only
`api.deleteMyData()` then `guest.rotate()`. The local store is not reset by
the deletion flow today.

**DECISION 14.** The deletion flow becomes: `api.deleteMyData()` →
`store.forgetGuest(guestId)` (now including preferences) →
`notifications.cancelReminder()` → `guest.rotate()`. Cancellation is
idempotent and runs even when the store is absent. A reminder never survives
deletion; the preference table never survives it either. This wires the
existing `forgetGuest` where it should already have been wired; it is in
scope because the reminder contract cannot be met without a local reset hook.

## 10. Compliance (Decision 15)

Only for what the code creates. No new health data, tracking, ad id,
contacts, location, camera or microphone.

| file | change |
|---|---|
| `compliance/permissions.v1.yaml` | `notifications.requested: true`, runtime, requested only after explicit opt-in, `deferred_to: null`; `push_notifications` stays `implemented: false` (local only); add `local_notifications: implemented: true, adapter: NotificationProvider, remote: false` |
| `compliance/third-party-sdks.v1.yaml` | add `flutter_local_notifications` (iOS + Android native, no network, no analytics); `timezone` under `dart_only_dependencies` |
| `compliance/data-inventory.v1.yaml` | `preferences` (local only, never sent, deletable); `personalization_provenance` (server, derived from session history, exported, deletable, `shown_to_user: reason only`); `ai.presentation_rewrite: path enabled, provider none engaged` |
| `compliance/retention.v1.yaml` | `local_preferences` (until deletion/uninstall), `personalization_provenance` (same as `sessions`) |
| `compliance/subprocessors.v1.yaml` | unchanged: no vendor engaged |
| `compliance/apple/…`, `compliance/google/…` | no new data category: preferences are local, provenance derives from already-declared session history; `check_compliance_consistency.py` must stay green |
| `AndroidManifest.xml`, `check_android_store_readiness.py` | every permission the merged-manifest audit shows the plugin contributes (expected `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`, `VIBRATE`) is added to `ALLOWED_PERMISSIONS` with its reason; `SCHEDULE_EXACT_ALARM` and `USE_EXACT_ALARM` join `PROHIBITED_PERMISSIONS` and are removed with `tools:node="remove"` if contributed |
| iOS | no `Info.plist` usage string exists for notifications; `PrivacyInfo.xcprivacy` is re-audited against the plugin's manifest by the existing check |

The permission list above is what the audit is expected to show, not an
assertion; the merged manifest decides and the gate records it.

## 11. Resource, performance and OCI boundaries

| limit | Program005 |
|---|---|
| implementation slices | 3 |
| backend services / microservices / queues / caches / vector DB / AI vendor adapters | 0 |
| server migrations | 1 (0008, one nullable column) |
| local DB migrations | 1 (sqflite 2 → 3, one table) |
| new Flutter runtime packages | 1 native plugin (+ `timezone`, pure Dart, see §9.1) |
| new backend API endpoints | 0 (two optional fields on existing request/response; export gains one key) |
| new settings screens | 1 |
| new CI jobs / platforms | 0 |

No Redis, Kafka, Celery, scheduler service or worker. Familiarity is one
bounded query inside the existing session-create transaction; nothing runs
between requests. OCI A1 (2 OCPU / 12 GB / 200 GB) is unaffected.

Benchmark: the stabilised `benchmark_paths.py` (ci-guard mode) gains one path,
`familiarity context query`, budget **50 ms** p95 on a seeded guest with 60
sessions of which 40 are completed for the practice. Existing budgets are
unchanged; `session create` (250 ms) now contains the extra query and stays
under its budget or the gate says so. Additional session-create queries: 1.
External AI is not a Program005 performance requirement; a future provider
adds its own path and budget.

## 12. Slices

**Slice A — backend familiarity, variants, provenance.** `ProtocolStage`
field + catalog validation; seven returning strings in `protocols.v2.yaml`;
`domain/personalization/` (`familiarity.py`, `presentation.py`,
`provenance.py`, `service.py`); definition schema 2; migration 0008;
`SessionRepository.completed_count`; `create_session` pipeline + invariant
check; request/response/export fields; benchmark path. Budget ≤ 16 production
files, ≤ 6 test files. Tests: PERS-01..08, 10, state-space and replay suites
unchanged and green.

**Slice B — reachable AI caller + client preference + explainability.**
`app.state.ai_provider`, `AIProviderDep`, guard wording checks, request
forbidden-key test, fallback reasons; sqflite schema 3 + `preferences`;
`adaptive_wording` in `createSession`; settings screen (preference only);
player line + transcript sheet detail. Budget ≤ 10 production files, ≤ 5 test
files. Tests: PERS-09, 11, 12; Dart schema 2→3 upgrade; preference round-trip;
request omits the field when default.

**Slice C — local reminder + compliance.** Interface extension;
`LocalNotificationProvider`; copy constants; window scheduler; settings
reminder group with the opt-in sheet; resume refresh; deletion-flow wiring;
pubspec, manifest, gate lists, compliance files. Budget ≤ 10 production
files, ≤ 4 test files. Tests: REM-01..08 with a fake provider recording
calls; the merged-manifest audit; compliance consistency.

A and B were kept separate because A is entirely server-side and reviewable
without a device toolchain; C is the only slice with native surface.

## 13. Acceptance

Tier: `CI` unless stated. Device axes (`NATIVE_INTEGRATION`, `ANDROID_DEVICE`,
`IOS_DEVICE`) may remain `NOT_RUN` and are never fabricated; the notification
actually appearing on a lock screen is a device fact.

| id | case | evidence |
|---|---|---|
| PERS-01 | first-time guest → `new`, canonical variant, `personalized=false` | API test |
| PERS-02 | guest with one completed session of the practice → `returning`, returning variant, `personalized=true`, `provider_id=null` | API test |
| PERS-03 | `practice_id` equal across NEW/RETURNING and across `adaptive_wording` on/off | API + §5.5 |
| PERS-04 | `duration_minutes`, `target_total_ms` equal | API + §5.5 |
| PERS-05 | stage count, order, ids, intents, silences, bell segments equal | plan comparison |
| PERS-06 | `familiarity_for(guest, practice)` reproduces tier and count from stored rows, incl. cap at 100 and abandoned sessions excluded | repository test |
| PERS-07 | `sessions.personalization` present, returned on create and GET, exported, schema as §7 | API test |
| PERS-08 | complete two more sessions → earlier session's response byte-identical | API test |
| PERS-09 | `adaptive_wording=false` → canonical, provider never invoked (spy), `fallback_reason=adaptive_wording_disabled` | API test with spy provider |
| PERS-10 | `AI_PROVIDER=null`, no key → valid session, `provider_absent` | API test |
| PERS-11 | injected provider changes `practice_id` / stage count / drops a placeholder / uses a medical term → deterministic wording, `envelope_violation` or `wording_rejected` | guard + API test |
| PERS-12 | injected provider raises / times out / returns garbage → session created, `provider_error` … | API test |
| REM-01 | fresh app, open settings → fake provider records zero permission calls | widget test |
| REM-02 | toggle on → sheet → Continue → exactly one `requestPermission` | widget test |
| REM-03 | granted → one `scheduleReminder(time)`; window of 14 ids | unit test on scheduler |
| REM-04 | change time → cancel + schedule with the same ids; no additional ids | unit test |
| REM-05 | toggle off → `cancelReminder`; preference `false` | widget + store test |
| REM-06 | denied → preference `false`, no schedule call, hint shown | widget test |
| REM-07 | delete data → `forgetGuest` (preferences gone) then `cancelReminder` then rotate | widget test with stub store |
| REM-08 | copy constants match §9.4 exactly; provider interface has no text parameter | unit test |

Regression: `test_state_space.py`, `test_v1_replay.py`, timing fixtures, all
Program004R suites unchanged and green; `flutter analyze --fatal-infos` green.

## 14. Required decisions — index

| # | decision | § |
|---|---|---|
| 1 | tiers: `new`, `returning` | 4.1 |
| 2 | threshold: ≥ 1 completed session of the practice; cap 100 | 4.2 |
| 3 | one bounded count on `ix_sessions_guest_id`, LIMIT 100 subquery, no new index | 4.3 |
| 4 | `returning_prompt_template` on `ProtocolStage`, in `protocols.v2.yaml` | 5.2 |
| 5 | first stage `prompt_template` only, ≤ canonical words, same placeholders | 5.1 |
| 6 | provenance object (§7) in `sessions.personalization` | 7 |
| 7 | AI call after variant selection, before definition freeze, in-request | 6.1 |
| 8 | one attempt, no retry, seven fallback reasons, variant wording kept | 6.4 |
| 9 | preferences in sqflite `preferences` table, not secure storage | 8 |
| 10 | local migration 2 → 3, one table | 8 |
| 11 | `flutter_local_notifications`, rolling 14-day one-shot window, inexact | 9.1 |
| 12 | permission only inside the toggle's opt-in flow | 9.3 |
| 13 | preference row is the record; OS schedule rebuilt on resume | 9.5 |
| 14 | deletion: server delete → `forgetGuest` → `cancelReminder` → rotate | 9.5 |
| 15 | compliance file changes as tabled | 10 |
| 16 | one server migration, 0008, nullable JSONB column | 7 |

## 15. Disposition

`PROGRAM005_PERSONALIZATION_SDD_READY_FOR_REVIEW`. Implementation begins
only after review, from this branch's merge into `main`, in the slice order
A → B → C.
