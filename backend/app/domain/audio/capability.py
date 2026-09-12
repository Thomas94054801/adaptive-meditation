"""Voice capability, classified from evidence rather than assumed.

Two corrections to the SDD are encoded here.

**Native TTS is not automatically offline.** On Android the system engine may
synthesise over the network, and the app cannot observe that directly. So a
voice is not called local because it is native; it is called local because a
probe with the network down produced audio. Until such a probe exists the
honest label is "unconfirmed", and an unconfirmed voice is still usable - it is
just not something we may claim offline support for.

**Localisation is not translation.** A locale is supported only when two
separate contracts both hold: approved content exists in that locale, and some
voice can speak it. Either one alone is a locale we must not offer. Shipping
English text read by a French voice, or a French translation with no voice to
read it, are different failures with the same cause: treating one contract as
evidence for the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OfflineCapability(StrEnum):
    """What a probe actually established about a voice."""

    LOCAL_CONFIRMED = "local_confirmed"
    """Rendered with the network unavailable. The only label that permits an
    offline claim."""

    LOCAL_UNCONFIRMED = "local_unconfirmed"
    """Rendered, but never with the network down. Probably local; unproven."""

    NETWORK_REQUIRED = "network_required"
    """Observed to fail without the network."""

    UNAVAILABLE = "unavailable"
    """Could not render at all."""


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """One empirical render attempt."""

    voice_id: str
    locale: str
    succeeded: bool
    network_available: bool
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if self.succeeded and self.duration_ms <= 0:
            raise ValueError(f"{self.voice_id}: a successful probe must have a duration")


def classify(observations: list[ProbeObservation]) -> OfflineCapability:
    """Classify a voice from what was observed, and nothing else.

    Order of evidence: a success with no network settles it; a failure with no
    network paired with a success with network settles the opposite; a success
    only ever seen with network is unconfirmed; anything else is unavailable.
    """
    if not observations:
        return OfflineCapability.UNAVAILABLE

    offline = [o for o in observations if not o.network_available]
    online = [o for o in observations if o.network_available]

    if any(o.succeeded for o in offline):
        return OfflineCapability.LOCAL_CONFIRMED
    if offline and not any(o.succeeded for o in offline):
        if any(o.succeeded for o in online):
            return OfflineCapability.NETWORK_REQUIRED
        return OfflineCapability.UNAVAILABLE
    if any(o.succeeded for o in online):
        return OfflineCapability.LOCAL_UNCONFIRMED
    return OfflineCapability.UNAVAILABLE


def may_claim_offline(capability: OfflineCapability) -> bool:
    """Whether a store listing or a privacy policy may say "works offline".

    Only one label qualifies. "Probably local" is not evidence, and a claim we
    cannot support is a compliance problem, not an optimism problem.
    """
    return capability is OfflineCapability.LOCAL_CONFIRMED


def is_usable(capability: OfflineCapability) -> bool:
    """Whether the voice can be offered at all."""
    return capability is not OfflineCapability.UNAVAILABLE


@dataclass(frozen=True, slots=True)
class VoiceCapability:
    voice_id: str
    locale: str
    offline: OfflineCapability
    provider_id: str

    @property
    def usable(self) -> bool:
        return is_usable(self.offline)


@dataclass(frozen=True, slots=True)
class LocaleSupport:
    """The two contracts, kept separate so neither can stand in for the other."""

    locale: str
    content_approved: bool
    """Approved guidance text exists in this locale. A machine translation of
    English is not approved content."""
    voices: tuple[VoiceCapability, ...]

    @property
    def has_voice(self) -> bool:
        return any(voice.usable for voice in self.voices)

    @property
    def supported(self) -> bool:
        """Offerable to a user. Requires both contracts, not either."""
        return self.content_approved and self.has_voice

    @property
    def offline_capable(self) -> bool:
        return self.supported and any(may_claim_offline(voice.offline) for voice in self.voices)

    def reason_unsupported(self) -> str:
        """Why this locale is not offered. For an operator, not a user."""
        if self.supported:
            return ""
        if not self.content_approved and not self.has_voice:
            return "no approved content and no voice"
        if not self.content_approved:
            return "a voice can speak it, but no approved content exists"
        return "approved content exists, but no voice can speak it"
