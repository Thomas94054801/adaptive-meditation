# PROGRAM005 — Personalization

## Guest-first adaptive presentation, familiarity and local reminders

Status: SDD, amended per PROGRAM005_SDD_AMEND_AND_IMPLEMENT (amendments A–E
folded in place; superseded designs deleted, not struck through).

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

Each must be visible: a returning guest hears a different opening and can
read why; a switch changes what they hear next; a reminder arrives at the time
they chose. Dormant interfaces are not personalization.

## 2. Frozen boundaries

### 2.1 Practice-selection authority

**FACT.** `create_session` (`backend/app/api/v1/routes.py:241`) re-derives the
recommendation from the stored check-in and rejects a submitted one that
differs (409 `recommendation_mismatch`). `RecommendationEngine` is pure: no
database, no provider.

**DECISION.** Nothing in Program005 — familiarity, preference, AI output,
reminder state, outcome evidence — is an input to `RecommendationEngine`,
`build_plan`'s allocation, duration/density selection, contraindications or
protocol identity; the envelope is computed before personalization and
compared after it (§5.5). The state-space and v1 replay suites and their
expected matrix are not regenerated.

### 2.2 Outcome score

**DECISION.** `session_feedback.outcome_score` remains a product optimisation
metric. Program005 reads no feedback row and no outcome field on any request
path; familiarity counts completed sessions (§4.2), never what the person
reported. No online learning loop: no model, training, reinforcement,
embedding or vector store.

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
Connect, wearables, biometrics, camera, microphone. Also push infrastructure,
device tokens, campaigns, remote schedulers, notification analytics, cloud
preference sync, profiles, quizzes, demographics.

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

All of it runs inside `create_session`, in one transaction, before the
`sessions` row is written; with the null provider the added cost is one
bounded query (§4.3) and no I/O.

## 4. Slice A — familiarity

### 4.1 Tiers

**DECISION 1.** Two tiers, `new` and `returning`: every protocol has exactly
one orientation stage (§5.1), so there is one thing to vary, and it either has
been heard before or has not.

### 4.2 Rule

**DECISION 2.** `personalization_policy_version = "1"`:

```text
evidence_count = completed sessions of this guest whose practice_id equals
                 the recommended practice_id, capped at EVIDENCE_CAP = 100
new        : evidence_count == 0
returning  : evidence_count >= 1
```

Threshold 1, not 2: the criterion is "has heard this orientation before", not
"is experienced". "Completed" is `sessions.status = 'completed'`, set by both
the feedback path and the playback `complete` command; abandoned sessions do
not count. The practice is the version-independent `practice_id`.

No guest identity (`OptionalGuestDep` is `None` and the check-in has no
guest) → `new`, `evidence_count = 0`, reason `no_history_available`.

What the evidence means: a completed session of this practice exists for
this guest. It does not claim the audio was heard, the technique was
understood, or any effect was obtained; the tier changes wording, nothing
more.

Familiarity depends on that one count and nothing else. It does not read
check-in values, feedback, notes, outcome fields, timestamps beyond ordering,
experiment arms or device facts. It infers no trait, no diagnosis and no
protected attribute, and the SDD forbids adding an input to it without a
policy-version bump.

### 4.3 Query and index

**FACT.** `sessions` has no `practice_id` column; the practice is
`recommendation->>'practice_id'` (JSONB on PostgreSQL, `models.py:25`). The
only index touching the predicate is `ix_sessions_guest_id`.

**DECISION 3.** One statement through the existing repository boundary,
counting at most 100 matches (`EVIDENCE_CAP`); rows are never loaded into
Python and filtered there:

```sql
SELECT count(*) FROM (
  SELECT 1 FROM sessions
   WHERE guest_id = :guest_id
     AND status = 'completed'
     AND recommendation->>'practice_id' = :practice_id
   LIMIT 100
) AS bounded;
```

`LIMIT 100` bounds the *output*, not the rows examined: without an index on
the full predicate the scan walks every row of the guest until 100 matches or
exhaustion, and a guest with a long history of other practices pays for all
of it. So migration 0008 carries, besides the column (§7), one expression
index matching the SQLAlchemy predicate exactly:

```sql
CREATE INDEX ix_sessions_familiarity
    ON sessions (guest_id, status, (recommendation ->> 'practice_id'));
```

Semantics of the result: `evidence_count = min(actual, 100)`;
`evidence_capped = (evidence_count == 100)` means "at least 100", never a
known total and never "more than 100". The tier is identical either side of
the cap.

Evidence required (Slice A): PostgreSQL tests with a dataset that mixes many
other practices, non-completed sessions of the target practice, and guests
with 0, 1 and > 100 matches; the migration applied and the index present;
and one `EXPLAIN (ANALYZE, BUFFERS)` summary for a seeded 10,000-row guest
kept under `docs/evidence/PROGRAM005/`. The planner is not forced: a small
table may legitimately seq-scan, and the test asserts the count, not the
plan. The SQLite path (portable JSON, `models.py:23`) keeps working through
the same SQLAlchemy expression; SQLite evidence does not substitute for
PostgreSQL evidence. The expression index is declared in the migration with
the PostgreSQL-only form the existing migrations already use for dialect
specifics; no generic index framework.

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

Speech length may change. The unchanged planner then estimates a shorter
speech for the returning `arrive` stage and gives the difference to that
stage's silence: the stage allocation, every other stage, the bell segments,
the requested duration and the silence-floor *algorithm* are untouched, and
the returning floor is never below the canonical floor for that stage. The
SDD does not require equal `target_ms`/`min_ms` across variants (that was the
original PERS-05 and is withdrawn) and does not touch planner or resolver to
force equality. Real synthesised length is Program004R resolution's business;
two different texts are not promised the same measured total.

Wording is checked by the public-language guard, the placeholder rules and
the word bound, and the seven strings were read sentence by sentence for
posture, walking and practice meaning. That review is a content decision;
none of the checks is a proof of semantic equivalence or of medical safety and
no such claim is made.

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

**FACT.** `SessionDefinition` (`timeline/definition.py`) is content-addressed
over `as_dict`, which already includes every stage's `prompt_template`;
`DEFINITION_SCHEMA_VERSION = 1` (`definition.py:21`). No test and no fixture
pins a literal `definition_id` or `plan_hash`.

**DECISION.** `DEFINITION_SCHEMA_VERSION` stays 1 and the serialisation and
hash format are unchanged. A returning session freezes a definition whose
first stage carries the returning text, so its `definition_id` differs from
the canonical one by construction; no `presentation_variant` field is added
to the definition. Variant, policy version, familiarity and AI attribution
live only in `sessions.personalization` (§7). The variant definition is built
as a new immutable `SessionDefinition`/`StageContent` object from the
catalog's protocol; the shared catalog is never mutated. Canonical bytes and
canonical `definition_id` are byte-identical before and after Program005, and
old sessions keep reading their frozen content. `source` stays `authored`
for both variants and becomes `generated` only for accepted provider wording
(§6.4).

Evidence: a fixture generated at the baseline commit (`367736a2`) holding
each practice's schema-1 canonical `definition_id`, canonical JSON bytes and
a `plan_hash` per (practice, duration) is committed under
`backend/tests/fixtures/`; the test round-trips it through the new code and
asserts no drift. Comparing two objects both produced by the new code is not
accepted as evidence.

### 5.5 Invariant check

**DECISION.** After personalization and before persisting, `create_session`
asserts, against the canonical definition for the same recommendation:
equal `practice_id`, `protocol_id`, `duration_minutes`, `guidance_density`,
stage count and order, and per stage equal `stage_id`, `intent`,
`silence_after_seconds`, `min_silence_seconds`, and every stage's
`prompt_template` except the first. A mismatch is a server defect (500,
logged without prompt text), never a silently different session. This is
what PERS-03/04/05 execute.

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
the envelope: `not_string`, `empty`, `length` (>600), `placeholders` (the
`${…}` set must equal the request's), `public_language`
(`assert_public_language`), and `protected_stage` — any stage other than the
first whose text differs from the request's, under policy 1. Any violation
keeps the request's wording for every stage; `GuardOutcome.violations` lists
what failed. A rejected result never reaches a definition, so the shared
content is never polluted. `strict=True` still raises for the provider suite.

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
provider that can produce one; the null provider returns its input and is
not counted as generative AI use (`ai_attempted=false`).

`provider_timeout` is recorded when the provider *raises* `TimeoutError`.
That is error handling, tested with a stub that raises; it is not an
implemented ability to abort an external model call. No thread pool, worker
or timeout framework is added for a network provider that does not exist.

### 6.5 Preference transport

**DECISION.** `SessionCreateRequest` gains `adaptive_wording: bool | None`
(absent → `true`, the default preference, so an older client is unchanged).
`false` selects the canonical variant and skips the provider call; the applied
value is frozen in provenance (§7). No backend preference table.

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
`reminder_minute`, `reminder_zone`. Not the secure store: the compliance note
describing that store as "one value" stays true, and an iOS keychain value
outlives uninstall by design. What the sqflite file actually does: on Android
`allowBackup=false` and `data_extraction_rules.xml` exclude every domain, so
nothing is backed up or transferred; on iOS the database sits in Application
Support, which the OS includes in device backups unless excluded, and
Program004R did not exclude it. So a preference can return with a restored
backup on iOS; "never survives uninstall" is not claimed. `forgetGuest` gains
`DELETE FROM preferences`. A write that fails is reported as a failure and the
switch returns to its stored value; turning adaptive wording off is read from
the table on every session create, so it holds across restarts.

Surface: one new screen, `features/settings/settings_screen.dart`, reached
from the history screen's app bar. The player shows one line under the title
when `personalized` is true ("Wording adapted: returning to this practice");
the transcript sheet shows variant, policy version and whether AI was used.

## 9. Slice C — local reminder

### 9.1 Mechanism and dependencies

**FACT.** `NotificationProvider` (`providers.dart:163`) exposes `isSupported`
and `requestPermission()`; the shipped implementation never touches a platform
API. No dependency in `pubspec.yaml` can schedule a notification.

**DECISION 11.** Three direct Flutter runtime dependencies — two native
plugins and one pure-Dart package — resolved against the app's own lockfile
in a scratch package on this toolchain (Flutter 3.47.3, Dart 3.13.3, AGP
9.1.0, Kotlin 2.4.0, Gradle 9.3.1, compileSdk/targetSdk 36, minSdk 24, iOS
15.0) with **no version change to any existing package**:

| package | constraint | resolved | role |
|---|---|---|---|
| `flutter_local_notifications` | `^22.3.0` | 22.3.1 | scheduling; Android + iOS native |
| `timezone` | `^0.11.1` | 0.11.1 | `TZDateTime` and named zones; pure Dart |
| `flutter_timezone` | `^5.1.0` | 5.1.0 | the OS IANA identifier; Android + iOS native |

Transitive additions: `flutter_local_notifications_platform_interface`
12.2.0, `_linux` 8.0.1, `_windows` 3.1.1, `_web` 1.0.0, `dbus` 0.7.15,
`equatable` 2.1.0, `petitparser` 7.0.2, `xml` 7.0.1 — no native code on
iOS or Android beyond the two plugins. A first-party AlarmManager/boot
receiver scheduler is refused for the reason Program004R refused a
first-party foreground service. The lockfile is the authority; the toolchain
is not upgraded to chase newer lines.

Native integration the 22.3.1 README requires, performed in Slice C:
core-library desugaring (`isCoreLibraryDesugaringEnabled`,
`desugar_jdk_libs`); `RECEIVE_BOOT_COMPLETED`; the
`ScheduledNotificationReceiver` / `ScheduledNotificationBootReceiver`
declarations; a monochrome notification drawable kept through the release
shrinker (`res/raw/keep.xml`); `UNUserNotificationCenter.current().delegate`
in `AppDelegate`. The plugin manifest contributes `POST_NOTIFICATIONS` and
`VIBRATE`; the merged-manifest audit records what appears.
`SCHEDULE_EXACT_ALARM`, `USE_EXACT_ALARM`, `USE_FULL_SCREEN_INTENT` and
`ACCESS_NOTIFICATION_POLICY` are prohibited.

**DECISION — schedule.** One reminder, one fixed id (`1`), via
`zonedSchedule(matchDateTimeComponents: DateTimeComponents.time,
androidScheduleMode: inexactAllowWhileIdle)`. The OS recurrence is the
schedule; the app never expires it. Delivery under battery saving, disabled
notifications or force-stop is not promised.

**DECISION — zone.** `tz.initializeTimeZones()` at bootstrap; the zone is
`FlutterTimezone.getLocalTimezone().identifier` via `tz.getLocation`. The
next instant is the next calendar occurrence of hour:minute in that zone —
not "now + 24 h", not UTC, not an abbreviation or fixed offset. An empty or
unknown identifier → "not scheduled", never a silent UTC schedule. On start
and resume the provider reads zone, effective permission and the pending
request and rewrites only when time, zone or enabled state changed or the
request is missing; no polling, no worker. DST inside one zone belongs to
the plugin's recurrence: on Android `ZonedDateTime.of` moves a spring-gap
time forward by the gap and takes the earlier offset in an autumn overlap
(read in the plugin source, not measured); on iOS
`UNCalendarNotificationTrigger` owns it and is `NOT_RUN`. A zone change is
corrected at the next start/resume; an app never reopened is not claimed to
follow the device zone.

**DECISION — state.** User intent (`reminder_enabled`), OS permission and
"actually scheduled" are three facts. "Reminder on" is shown only when
scheduling succeeded; a failure shows with a retry. Android 13+:
`requestNotificationsPermission()`; below 13 no prompt and
`areNotificationsEnabled()` is the truth (app or channel disabled → not
granted). iOS: `checkPermissions()` / `requestPermissions(alert, sound)`.

### 9.2 Interface

**DECISION.** The smallest extension, no second abstraction:

```dart
enum ReminderPermission { granted, denied, undetermined, unsupported }
class ReminderTime { final int hour; final int minute; }
class ReminderSchedule { final ReminderTime time; final String zoneId; }
abstract interface class NotificationProvider {
  bool get isSupported;
  Future<ReminderPermission> permissionState();
  Future<bool> requestPermission();
  Future<String?> localZoneId();                     // IANA, null if unknown
  Future<void> scheduleReminder(ReminderSchedule s); // id 1, replaces
  Future<ReminderSchedule?> scheduledReminder();     // what the OS holds
  Future<void> cancelReminder();
}
```

`DisabledNotificationProvider` stays inert (`unsupported`, `false`, no-ops)
for tests; on Android and iOS `bootstrap.dart` injects
`LocalNotificationProvider`, and the production-wiring audit
(`auditProductionAdapters`) lists the disabled provider as forbidden on those
platforms, so it cannot become the production default by omission. iOS
initialisation passes `requestAlertPermission: false`,
`requestBadgePermission: false`, `requestSoundPermission: false`; the only
call that can show the OS prompt is `requestPermission()`, and the only caller
is the settings toggle's Continue button. The interface has no text
parameter: the copy is a constant inside the provider (§9.4).

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

Never on first launch, onboarding, opening settings, plugin initialisation,
app resume or upgrade. Denial is a normal state. If the OS permission is
later revoked, the intent stays as set, the settings screen shows the
system-settings hint and "not scheduled", and nothing prompts. Platform
calls are as in §9.1; below Android 13 the effective enabled state is read,
not assumed.

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

**DECISION 13.** The preference row (`reminder_enabled`, hour, minute, zone)
is the record of intent; the OS pending request is derived state, reconciled
on start/resume (§9.1).

**FACT.** `DurableStore.forgetGuest` (`durable_store.dart:549`) clears
outbox, checkpoints and feedback and writes the tombstone, but
`showDeleteDataDialog` (`delete_data_dialog.dart:48-51`) calls only
`api.deleteMyData()` then `guest.rotate()`: deletion leaves every local table
in place today. A Program004R gap, not a preferences one.

**DECISION 14.** Deletion is a resumable local procedure, not a chain of
unguarded awaits. Its state is the existing `deleted_guests` tombstone plus
at most one `deletion_pending` row in `preferences` — no new table, no worker.

```text
confirm
  1. deletion_pending = guest_id; reminder_enabled = false
     → no new outbox/checkpoint/feedback writes, no sync, no reminder
       reconcile for this guest from here on
  2. cancelReminder()                (no network; failure recorded, not fatal)
  3. DELETE /v1/me/data with the ORIGINAL identity
  4. on 3 success: forgetGuest(guest_id) (tables + preferences + tombstone)
  5. only when 2, 3 and 4 are all confirmed: rotate identity, clear the
     marker, report "all data deleted"
```

A failed step leaves the marker set and the identity unrotated, so the retry
uses the same guest id and the dialog says which step failed; steps that can
still run do run. On the next start the marker resumes from the first
unconfirmed step. Tombstone and marker fence late responses and reconcile:
nothing recreates rows or re-schedules a reminder for a guest under
deletion. The three external operations are idempotent already (`DELETE` on
an absent guest is 404 and counts as done; `forgetGuest` deletes by table;
`cancel(id)` on nothing is a no-op) and the tests assert it. No saga, no
distributed transaction.

## 10. Compliance (Decision 15)

Only for what the code creates. No new health data, tracking, ad id,
contacts, location, camera or microphone.

| file | change |
|---|---|
| `compliance/permissions.v1.yaml` | `notifications.requested: true`, runtime, requested only after explicit opt-in, `deferred_to: null`; `push_notifications` stays `implemented: false` (local only); add `local_notifications: implemented: true, adapter: NotificationProvider, remote: false` |
| `compliance/third-party-sdks.v1.yaml` | add `flutter_local_notifications` 22.3.1 and `flutter_timezone` 5.1.0 (native, no network, no analytics); `timezone` under `dart_only_dependencies` |
| `compliance/data-inventory.v1.yaml` | two separate entries: `reminder_preference` (enabled/hour/minute/zone — device only, never sent) and `adaptive_wording_preference` (device store; the value is **sent** on every session-create request, the applied value is **stored** in `sessions.personalization` and **exported**); `personalization_provenance` (server, derived from session history, exported, deletable, `shown_to_user: reason only`); `ai.presentation_rewrite: path enabled, provider none engaged`; backup statement as §8 |
| `compliance/retention.v1.yaml` | `local_preferences` (until deletion; iOS backup caveat), `personalization_provenance` (same as `sessions`) |
| `compliance/subprocessors.v1.yaml` | unchanged: no vendor engaged |
| `compliance/apple/…`, `compliance/google/…` | updated from the real flow, not assumed unchanged: the adaptive-wording value travels with session creation under the already-declared session/history category; reminder settings are device-only; no health data and no third-party transfer are added; `check_compliance_consistency.py` must stay green |
| `AndroidManifest.xml`, `check_android_store_readiness.py` | `RECEIVE_BOOT_COMPLETED` declared by the app; `POST_NOTIFICATIONS` and `VIBRATE` from the plugin manifest; each added to `ALLOWED_PERMISSIONS` with its reason as the merged-manifest audit confirms them; `SCHEDULE_EXACT_ALARM`, `USE_EXACT_ALARM`, `USE_FULL_SCREEN_INTENT`, `ACCESS_NOTIFICATION_POLICY` join `PROHIBITED_PERMISSIONS` |
| iOS | no `Info.plist` usage string exists for notifications; `PrivacyInfo.xcprivacy` is re-audited by the existing check |

The permission list above is what the audit is expected to show, not an
assertion; the merged manifest decides and the gate records it.

## 11. Resource, performance and OCI boundaries

| limit | Program005 |
|---|---|
| implementation slices | 3 |
| backend services / microservices / queues / caches / vector DB / AI vendor adapters | 0 |
| server migrations | 1 (0008: one nullable column + one expression index) |
| local DB migrations | 1 (sqflite 2 → 3, one table; deletion marker lives in it) |
| new Flutter runtime packages | 3 direct: 2 native plugins + 1 pure Dart (§9.1) |
| new backend API endpoints | 0 (two optional fields on existing request/response; export gains one key) |
| new settings screens | 1 |
| new CI jobs / platforms | 0 |
| source / test unique files | estimate 24 / 12; deviations explained, not padded |

No Redis, Kafka, Celery, scheduler service or worker; nothing runs between
requests. OCI A1 (2 OCPU / 12 GB / 200 GB) is unaffected.

Benchmark: the stabilised `benchmark_paths.py` (ci-guard mode) gains one path,
`familiarity context query`, budget **50 ms** p95 — a controlled-environment
design target; the hosted runner only guards for an order-of-magnitude
regression and is never reported as OCI performance. The seeded guest has a
sparse history (many other-practice and abandoned rows, few matches) so the
index, not the cap, is what the number reflects. Existing budgets are
unchanged; `session create` (250 ms) now contains the extra query.
Additional session-create queries: 1.
External AI is not a Program005 performance requirement; a future provider
adds its own path and budget.

## 12. Slices

**Slice A — end-to-end personalization core.** `ProtocolStage` field +
catalog validation; seven returning strings in `protocols.v2.yaml`; one
small `domain/personalization.py` (tier, variant definition, provenance,
the guarded provider call) rather than a service/manager/registry stack;
migration 0008 (column + index); `SessionRepository.completed_count`;
`create_session` pipeline + invariant check; request/response/export fields;
`app.state.ai_provider`/`AIProviderDep` with the null provider; guard
extension; benchmark path; baseline fixture. Tests: PERS-01..12, query
evidence, fixture round-trip, 7 × 5 plan comparison; state-space and replay
suites unchanged and green.

**Slice B — preference and visible effect.** sqflite schema 3 +
`preferences`; `adaptive_wording` in `createSession`; settings screen
(preference switch); player line + transcript sheet detail. Tests: schema
2→3 keeps checkpoints/outbox/feedback; close-and-reopen persistence; a
failed write is not reported as success; the request carries the stored
value.

**Slice C — local daily reminder + deletion recovery + disclosure.**
Interface extension; `LocalNotificationProvider` (zone, permission, single
id, reconcile); copy constants; settings reminder group with the opt-in
sheet; start/resume reconcile; the deletion procedure of §9.5 including
`forgetGuest`; pubspec + lockfile, Gradle desugaring, manifest receivers,
`keep.xml`, `AppDelegate`, gate lists, compliance files. The local deletion
repair does not wait on the plugin: if Slice C's native integration were
blocked, the store wiring still lands. Tests: REM-01..08 with a fake
provider recording calls; deletion failure/recovery matrix; merged-manifest
audit; compliance consistency.

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
| PERS-05 | for 7 practices × 5 durations: stage count/order/ids/intents, `silence_after_seconds`, `min_silence_seconds`, bell segments, `target_total_ms` equal; every non-first stage's text equal; returning `arrive` silence floor ≥ canonical floor; no other stage's timing differs | plan comparison |
| PERS-06 | count reproduces tier from stored rows: 0 / 1 / > 100 matches, cap saturation, abandoned excluded, other guest and other practice isolated, sparse history; index present after migration; PostgreSQL | repository test + EXPLAIN evidence |
| PERS-07 | `sessions.personalization` present, returned on create and GET, exported, schema as §7 | API test |
| PERS-08 | complete two more sessions → earlier session's response byte-identical | API test |
| PERS-09 | `adaptive_wording=false` → canonical, provider never invoked (spy), `fallback_reason=adaptive_wording_disabled` | API test with spy provider |
| PERS-10 | `AI_PROVIDER=null`, no key → valid session, `provider_absent` | API test |
| PERS-11 | injected provider changes `practice_id` / stage count / a non-first stage / drops a placeholder / empty / non-string / > 600 chars / medical term → deterministic wording, `envelope_violation` or `wording_rejected`; no definition row from the rejected text | guard + API test |
| PERS-12 | injected provider raises / raises `TimeoutError` / returns a malformed result → session created, `provider_error` / `provider_timeout` / `malformed_output` | API test |
| PERS-13 | schema-1 baseline fixture: canonical bytes, `definition_id` and `plan_hash` round-trip without drift | fixture test |
| REM-01 | fresh app, open settings → fake provider records zero permission calls | widget test |
| REM-02 | toggle on → sheet → Continue → exactly one `requestPermission` | widget test |
| REM-03 | granted → one `scheduleReminder` with id 1 in the resolved IANA zone; next instant is the next calendar occurrence, not now + 24 h | unit test with fake zone |
| REM-04 | change time or zone → the same id is rewritten; unchanged state → no rewrite on resume; nothing expires after 14 days | unit test |
| REM-05 | toggle off → `cancelReminder`; preference `false` | widget + store test |
| REM-06 | denied / revoked / pre-13 disabled → intent unchanged where set, nothing scheduled, hint shown, no prompt | widget test |
| REM-07 | deletion matrix: server fails → marker kept, identity kept, retry works; local write fails → not reported as success; cancel fails → server delete and purge still run; all succeed → rotate; restart with marker → resumes; late reconcile with marker → no reschedule, no recreated rows | widget + store tests |
| REM-09 | unknown zone → "not scheduled", no UTC fallback | unit test |
| REM-10 | Android/iOS DST gap and overlap behaviour | NOT_RUN (no device); Android policy read from plugin source only |
| REM-08 | copy constants match §9.4 exactly; provider interface has no text parameter | unit test |

Regression: `test_state_space.py`, `test_v1_replay.py`, timing fixtures, all
Program004R suites unchanged and green; `flutter analyze --fatal-infos` green.

## 14. Required decisions — index

| # | decision | § |
|---|---|---|
| 1 | tiers: `new`, `returning` | 4.1 |
| 2 | threshold: ≥ 1 completed session of the practice; cap 100 | 4.2 |
| 3 | COUNT-over-LIMIT-100 through the repository + `ix_sessions_familiarity (guest_id, status, (recommendation->>'practice_id'))` in 0008; saturation semantics | 4.3 |
| 4 | `returning_prompt_template` on `ProtocolStage`, in `protocols.v2.yaml` | 5.2 |
| 5 | first stage `prompt_template` only, ≤ canonical words, same placeholders | 5.1 |
| 6 | provenance object (§7) in `sessions.personalization`; definition schema stays 1 | 7, 5.4 |
| 7 | AI call after variant selection, before definition freeze, in-request | 6.1 |
| 8 | one attempt, no retry, seven fallback reasons, variant wording kept | 6.4 |
| 9 | preferences in sqflite `preferences` table, not secure storage | 8 |
| 10 | local migration 2 → 3, one table | 8 |
| 11 | `flutter_local_notifications` 22.3.1 + `timezone` 0.11.1 + `flutter_timezone` 5.1.0; one id, `zonedSchedule` + `DateTimeComponents.time`, inexact, IANA zone | 9.1 |
| 12 | permission only inside the toggle's opt-in flow | 9.3 |
| 13 | preference row is the record of intent; OS request reconciled on start/resume | 9.5 |
| 14 | resumable deletion with tombstone + `deletion_pending` marker; rotate only after all steps confirm | 9.5 |
| 15 | compliance file changes as tabled | 10 |
| 16 | one server migration, 0008: nullable JSONB column + expression index | 7, 4.3 |

## 15. Disposition

Amended in place under PROGRAM005_SDD_AMEND_AND_IMPLEMENT; implementation
follows on this branch in the order A → B → C, in bounded commits, without a
second design review. Disposition is reported by the implementation task,
five axes apart, with device and human axes `NOT_RUN` until measured.
