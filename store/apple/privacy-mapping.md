# Apple App Privacy — how each answer was derived

The machine-readable answers are in `compliance/apple/app-privacy.v1.yaml`, and
CI fails if they disagree with `compliance/data-inventory.v1.yaml`. This file
records the reasoning a reviewer would otherwise have to reconstruct.

## Tracking: No

Apple's definition is linking this app's data with data from other companies'
apps or websites for advertising or measurement, or sharing it with a data
broker. The app contains no advertising SDK, no attribution SDK and no
third-party analytics, and holds no identifier that could perform such a join.

Consequence: no App Tracking Transparency prompt, and every
`NSPrivacyCollectedDataTypeTracking` flag is false.

## Identifiers → User ID: collected, linked, not tracking

A random UUIDv4 generated on the device and stored in the Keychain.

- *Collected*, because it is sent to the backend with each request.
- *Linked*, because the user's own history hangs off it — pretending otherwise
  would understate what it does.
- *Not tracking*, because it is never joined with anything outside this product.

Device ID is answered explicitly as not collected: no IDFA, no IDFV, no
fingerprint.

## User Content → Other User Content

Check-ins, session records and feedback. Feedback includes an optional free-text
note, which is what makes this User Content rather than Usage Data.

## Usage Data → Product Interaction

Derived outcome measures and experiment assignments. Used to evaluate whether
recommendations work, offline and in aggregate.

## Health and Fitness: not declared

The self-reported numbers are stress, energy, mental activity and sleepiness
typed in by the user. Nothing is read from HealthKit, and no health entitlement
is requested.

Declaring Health and Fitness would be inaccurate and would invite scrutiny of an
entitlement the app does not hold. The honest category is Other Data.

## Diagnostics: not collected

No crash reporting SDK is integrated. Server-side operational logs contain
request identifiers and status codes, are retained 30 days, and carry no guest
identifier and no user content — so there is nothing collected from the device
to declare.

## Required Reason APIs: none at app level

The app's own binary uses none. The identifier lives in the Keychain, which is
not a Required Reason API. `shared_preferences`, whose UserDefaults access would
have required CA92.1, was removed when the identifier moved to secure storage.

The Flutter engine and each plugin ship their own manifests, which Xcode
aggregates; re-declaring their usage at app level would misattribute it.
