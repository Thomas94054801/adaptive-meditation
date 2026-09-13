# App Review notes — Google Play

## No account is needed

The app works entirely without signing in. There are no accounts, so there is no
test account to provide. Open the app and tap **Start a session**.

## What the app does

The user reports how they feel on six short questions. A deterministic rules
engine selects a meditation practice matching that state, builds a session for
the available time, and guides them through it with on-screen text. Afterwards
the user reports how they feel and rates the session.

## Reviewing the core flow, in about three minutes

1. **Welcome** — tap *Start a session*.
2. **Check-in** — choose a goal, set the four sliders, pick 3 minutes for the
   fastest review, choose an experience level, tap *See my practice*.
3. **Recommendation** — practice name, duration and a plain-English reason. Tap
   *Start*.
4. **Session player** — stage text, progress, pause/resume, *End session*.
   *End session* goes straight to feedback without waiting for the timer.
5. **Feedback** — four scales, a usefulness rating, an optional note, *Done*.
6. **History** — *Recent sessions* on the welcome screen.

## Data deletion

Play's account-deletion requirement is about apps that let users create an
account. This app does not. Guest data deletion is implemented regardless,
because the data exists whether or not an account does:

**Your sessions → Delete my meditation data** deletes the user's check-ins,
sessions, feedback and experiment assignments from the service permanently,
after one confirmation, with no waiting period. The device then starts with a
new identifier.

A web description of the same path is served at `/privacy-choices`.

## Data safety declaration

Mapped from the code in `compliance/google/data-safety.v1.yaml`. In summary:
data is collected, none is shared, everything is encrypted in transit, and the
user can delete all of it from inside the app.

## Permissions

`INTERNET` only. The merged release manifest is checked in CI
(`scripts/check_android_store_readiness.py`) against a prohibited list that
includes camera, microphone, location, body sensors, activity recognition,
contacts and the advertising ID permission.

## Advertising ID

Not requested and not used. There is no advertising in the app and no
attribution SDK.

## Health data

Health Connect is not integrated. The wellbeing numbers are self-reported values
the user typed in, declared as user-generated content rather than health data.

## Target API

`targetSdkVersion` is pinned to 36 as a literal in `build.gradle.kts`, and CI
fails the build if it drops below the Play requirement.

## Medical positioning

A wellness and mindfulness app. No diagnostic or treatment claim appears in the
product or the listing. The terms state that it is not a medical service and
cannot help in an emergency.

## Commerce

No subscription, no in-app purchase, no ads in this version.
