# PROGRAM005 status — Personalization

Disposition:
`PROGRAM005_DEVICE_INDEPENDENT_IMPLEMENTED_CI_GREEN_PENDING_NATIVE_DEVICE_AND_HUMAN_VALIDATION`

| | |
|---|---|
| baseline `main` | `367736a2d4269ac1a951d82e5fb0233d1d59238f` |
| SDD (amended in place) | `docs/sdd/PROGRAM005-personalization.md`, amendment commit `7061cf93` |
| implementation | `c320efe` (Slice A) → `26ce9b7` (Slice B) → `31c0a4c1` (Slice C) |
| PR | #6, `program005/personalization-sdd` → `main`, open |
| CI on `31c0a4c1` | push `34850883791` SUCCESS, pull_request `34850887702` SUCCESS, 6/6 jobs; 606 backend, 272 Flutter |
| evidence | `docs/evidence/PROGRAM005/acceptance.v1.json` (32 PASS, 1 NOT_RUN), `familiarity_explain.v1.txt` |

## Five axes

```
CI                  = PASS      (runs above)
NATIVE_INTEGRATION  = NOT_RUN   (release AAB and no-codesign iOS build succeed; nothing ran on a device)
ANDROID_DEVICE      = NOT_RUN   (reminder delivery, reboot re-registration, DST recurrence)
IOS_DEVICE          = NOT_RUN   (same, plus UNCalendarNotificationTrigger gap/overlap)
HUMAN_LISTENING     = NOT_RUN   (the returning opening has not been heard)
STORE_RELEASE_READINESS = BLOCKED
```

## What is done

- **Familiarity** — two tiers, threshold one completed session of the same
  practice, one COUNT-over-LIMIT-100 query on `ix_sessions_familiarity`
  (migration 0008, with the nullable `sessions.personalization` column).
  EXPLAIN on a 10,000-row guest: 3 buffers with the index, a 10,399-row
  filter without it.
- **Returning opening** — seven first-stage templates in `protocols.v2.yaml`,
  validated at load; definition schema stays 1 and a fixture generated at the
  baseline by the old code pins every canonical definition and all 35 plan
  hashes.
- **Provenance** — written once, returned on create/GET, exported; the
  player shows one line and the transcript names variant, reason, policy and
  AI use. The null provider is never reported as AI use.
- **AI path** — `build_ai_provider` reachable from session create; the guard
  refuses any change outside the first stage; one attempt, no retry; no
  vendor, no external call.
- **Preference** — one switch in a new sqflite `preferences` table (schema
  2 → 3), sent with session create, frozen with the session.
- **Reminder** — one daily OS recurrence at id 1 in the device's IANA zone
  (`flutter_local_notifications 22.3.1`, `timezone 0.11.1`,
  `flutter_timezone 5.1.0`; no other package version moved). Permission only
  from the opt-in sheet. Unknown zone → not scheduled, never UTC. Nothing in
  the app expires it.
- **Deletion** — a resumable procedure that finally calls `forgetGuest`,
  cancels the reminder without waiting on it, and rotates the identity only
  after every step confirmed.

## Not done, and why

- Nothing has run on an Android or iOS device or simulator: whether a
  reminder is delivered, survives a reboot, or follows a DST change is
  unmeasured. The plugin's Android recurrence was read in its source; iOS's
  was not exercised at all.
- The release AAB grew from 53.8 MB to 55.4 MB (the two plugins and the
  zone database). APK and installed footprint were not measured.
- The SQLite migration chain was already broken at the baseline by 0007's
  `ALTER … ADD CONSTRAINT`; 0008 is SQLite-valid and this program did not
  patch an applied migration. CI runs PostgreSQL.
- File budget: 33 source and 17 test files against estimates of 24 and 12;
  the acceptance file lists every one and the reason.
