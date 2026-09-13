# App Review notes — Apple

## No account is needed

Everything in this app works without signing in. There is no demo account
because there are no accounts at all. Open the app and tap **Start a session**.

## What the app does

You report how you feel right now on six short questions. A deterministic rules
engine selects a meditation practice that matches that state, builds a session
for the time you said you had, and guides you through it with on-screen text.
Afterwards you report how you feel and rate the session.

## Reviewing the core flow, in about three minutes

1. **Welcome** — tap *Start a session*. No sign-in appears.
2. **Check-in** — pick a goal, move the four sliders, choose a duration
   (3 minutes is the quickest to review) and an experience level, then tap
   *See my practice*.
3. **Recommendation** — the app names the practice, the duration, and explains
   in plain English why it chose that one. Tap *Start*.
4. **Session player** — stage text, a progress bar, pause/resume and
   *End session*. Tapping *End session* goes straight to feedback, so you do not
   need to wait out the timer.
5. **Feedback** — the same four scales again, a usefulness rating, an optional
   note. Tap *Done*.
6. **History** — from the welcome screen, *Recent sessions* shows the session
   you just completed.

## Exporting and deleting data

Both are in the app, not behind a support request:

- **Your sessions → Export my meditation data** returns everything stored for
  this device as JSON.
- **Your sessions → Delete my meditation data** permanently deletes it after a
  single confirmation, and the device then starts with a new identifier.

## Privacy

The only stored identifier is a random UUID generated on the device and held in
the Keychain. It is not the IDFA, not the IDFV, and not derived from the device
in any way. The app requests no camera, microphone, location, contacts, photo or
health permission, and there is no App Tracking Transparency prompt because the
app does not track.

`PrivacyInfo.xcprivacy` is included in the bundle. The audit behind it is in the
repository at `compliance/apple/privacy-manifest-audit.v1.yaml`.

## Health data

None. HealthKit is not enabled and no health entitlement is requested. The
numbers you see are self-reported values the user typed in, which is why the
privacy manifest declares them as Other Data rather than Health and Fitness.

## Medical positioning

This is a wellness and mindfulness app. It makes no diagnostic or treatment
claim anywhere in the product or the listing. The terms of use state plainly
that it is not a medical service and cannot help in an emergency, and the app
shows a wellness disclaimer before first use.

## Commerce

No subscription, no in-app purchase, no advertising in this version.

## Third-party SDKs

Two: `flutter_secure_storage` for Keychain access, and `http` for calls to this
app's own backend. No analytics, attribution, advertising or crash-reporting SDK
is present. The full inventory is at `compliance/third-party-sdks.v1.yaml`.

## Network

The app talks only to its own backend over HTTPS. There are no ATS exceptions.
