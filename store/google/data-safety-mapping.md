# Google Play Data Safety — how each answer was derived

The machine-readable answers are in `compliance/google/data-safety.v1.yaml`, and
CI fails if they disagree with `compliance/data-inventory.v1.yaml`.

## Summary answers

| Question | Answer | Why |
|---|---|---|
| Does your app collect or share user data? | Collects, does not share | Data reaches this product's own backend and goes nowhere else |
| Is all data encrypted in transit? | Yes | HTTPS only; the release network config forbids cleartext with no exception |
| Do you provide a way to delete data? | Yes | In-app, immediate, hard delete by database cascade |
| Independent security review? | No | None has been performed, and claiming one is a false declaration a reviewer can ask us to evidence |
| Play Families policy commitment? | No | The app is for adults and is not in a Families programme |

## Personal info → User IDs

The random guest UUID. Marked required, because it is the only way the user's
own history and their deletion request can be located. Not shared, not
ephemeral, deletable.

## App activity → Other user-generated content

Check-ins and feedback. Feedback is marked optional: a session can be completed
without giving any.

## App activity → App interactions

Session history, outcome evidence and experiment assignments.

## Device or other IDs: not collected

No advertising ID, no GAID, no hardware identifier. The guest identifier is
app-generated, so it belongs under Personal info → User IDs rather than here.
Getting this wrong in the other direction is a common cause of Data Safety
rejections.

## Health and fitness: not collected

Health Connect is not integrated. The self-reported wellbeing numbers are
declared as user-generated content.

## App info and performance → Crash logs: not collected

No crash reporting SDK. If one is ever added, this answer, the Apple mapping,
the SDK inventory and the data inventory all change together — which is what the
consistency check in CI enforces.

## Account deletion

Play requires an account deletion path for apps offering account creation. This
app offers none, so the requirement does not apply. Guest data deletion is
implemented anyway and is reachable in-app and described at `/privacy-choices`.
