# Mobile App

Flutter client for iOS and Android. Target stores: Apple App Store, Google Play.

## Layout

```text
lib/
  main.dart
  app/            app shell, theme, AppScope dependency holder
  core/           config, wire models, API client, reason-code wording
  features/
    welcome/      guest entry, no registration wall
    check_in/     goal, stress, energy, mental activity, sleepiness, time, experience
    recommendation/  public practice title, duration, plain-English reason
    session/      deterministic player (session_timeline.dart is pure logic)
    feedback/     before/after and helpfulness
    history/      local list of sessions from this run
  platform/       AuthProvider, BillingProvider, TtsProvider, SecureStorageProvider,
                  NotificationProvider, HealthProvider - interfaces with inert V1
                  implementations and no call sites
```

## The client does not choose the practice

The check-in goes to the backend and the recommendation comes back. The app does
not send a recommendation when creating a session: the server re-derives it, and
a disagreement is a 409. Internal source mappings are never displayed, and a
reason code the client does not recognise is dropped rather than shown raw.

## Permissions

`INTERNET` is the only permission declared. Camera, microphone, location,
contacts, photo library, notifications, HealthKit and Health Connect are absent
from both manifests; `test/permissions_manifest_test.dart` asserts that against
`compliance/permissions.v1.yaml`, so a plugin cannot add one unnoticed.

Bundle identifiers are set per platform and are not derived from the publisher's
legal name, so moving from an individual publisher to a company later does not
require a rewrite.

## Running it

```bash
flutter pub get
flutter run --dart-define=API_BASE_URL=http://localhost:8000
flutter analyze
flutter test
```

No API key is compiled into the client; the backend needs no client credential
in Program001.
