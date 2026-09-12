/// The audio-session port — focus, routes and background playback.
///
/// Behind an interface for the same reason every other platform capability is:
/// the widget tests must run without a device, and a store-sensitive capability
/// must be swappable without the session domain knowing.
///
/// This port is the reason the app now declares background audio. Playing while
/// the screen is off is not an optimisation here - a meditation the user has to
/// keep the phone unlocked for is a meditation spent watching a phone.
library;

/// Where sound is coming out. Coarse on purpose: the distinction that matters
/// is private versus audible to the room.
enum AudioRoute {
  speaker('speaker'),
  receiver('receiver'),
  headphones('headphones'),
  bluetooth('bluetooth'),
  car('car'),
  airplay('airplay'),
  unknown('unknown');

  const AudioRoute(this.wireValue);

  final String wireValue;

  /// Whether only the listener hears it.
  ///
  /// Unknown counts as audible to the room. Guessing wrong that way pauses a
  /// session; guessing wrong the other way broadcasts one.
  bool get isPrivate =>
      this == headphones || this == bluetooth || this == receiver;
}

/// Why playback should stop without the user asking.
enum AudioInterruption {
  /// A call, an alarm, another app taking audio.
  focusLost('focus_lost'),

  /// Headphones or Bluetooth gone, and the fallback would be audible to
  /// everyone in the room.
  wentPublic('went_public');

  const AudioInterruption(this.wireValue);

  final String wireValue;
}

/// What a platform audio session can do.
abstract class AudioSessionPort {
  /// Claim audio focus. False means another app has it and we must not play.
  Future<bool> activate();

  /// Release focus, so a paused session stops ducking other audio.
  Future<void> deactivate();

  /// The current output route.
  Future<AudioRoute> currentRoute();

  /// Interruptions, as they happen.
  Stream<AudioInterruption> get interruptions;

  /// Focus coming back. Never resumes playback on its own - it exists so the
  /// UI can offer the choice.
  Stream<void> get focusRegained;

  /// Route changes, for the journal and for the privacy rule.
  Stream<AudioRoute> get routeChanges;
}

/// Decides what a route change means. Mirrors the backend policy exactly.
AudioInterruption? interruptionForRouteChange(
  AudioRoute previous,
  AudioRoute current,
) {
  if (previous == current) {
    return null;
  }
  if (previous.isPrivate && !current.isPrivate) {
    return AudioInterruption.wentPublic;
  }
  return null;
}
