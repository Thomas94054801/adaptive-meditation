# Adaptive Meditation

US-first AI adaptive mindfulness and meditation platform.

## Product thesis

The product translates a source-grounded contemplative practice system into accessible, non-sectarian Western wellness language. The user starts with a current-state check-in; the system selects a suitable practice protocol; AI may personalize wording and voice but does not own the practice decision.

## Program001 — Foundation

Initial vertical slice:

1. English onboarding
2. State check-in
3. State → practice selection
4. Structured 5-minute practice protocol
5. Session execution
6. Before/after feedback
7. Session history

## Architecture principles

- Individual-first commercial launch; incorporation only after real subscription/revenue validation.
- US-first, English-first, with EU readiness designed but not allowed to block MVP.
- Wellness/mindfulness positioning; no medical diagnosis or treatment claims.
- Flutter client target for iOS and Android.
- FastAPI + PostgreSQL backend sized for the existing OCI A1 2 OCPU / 12 GB / 200 GB environment.
- OCI is the control/data plane, not a large-model GPU inference host.
- Provider-neutral AI and TTS adapters.
- Canonical practice knowledge and protocol selection remain deterministic/source-grounded; generative AI personalizes presentation only.
- HealthKit/Health Connect/camera/biometric inference are deferred until after V1 store release.
- Privacy, deletion, export, AI safety, store declarations and subscription entitlement are architecture concerns from day one.

## Programs

- Program001: Platform Foundation
- Program002: Practice Intelligence
- Program003: Individual-first Commercialization & Store Compliance
- Program004: Core Adaptive Meditation Experience
- Program005: Personalization
- Program006: Commerce
- Program007: Apple/Google Store Release
- Program008: Optional Health Integrations

## Status

Program001 bootstrap in progress.
