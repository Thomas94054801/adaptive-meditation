/// The playback port.
///
/// Deliberately narrow: load a list of verified local media, play it, and
/// report what actually happened. It knows nothing about sessions, plans or
/// guests. Everything it reports is device-observed, and the naming says so —
/// `SegmentLifecycle.completed` means the player said a medium finished, not
/// that anyone heard it.
library;

/// One playable piece of a session.
class PlayableSegment {
  const PlayableSegment({
    required this.segmentId,
    required this.uri,
    required this.expectedMs,
    required this.kind,
    this.isRequired = true,
  });

  final String segmentId;

  /// A verified local `file:` or `asset:` URI. Remote URLs are out of scope
  /// for this package, so this can never be a network source.
  final String uri;

  final int expectedMs;

  /// `speech`, `silence` or `bell`. The runtime needs the distinction because
  /// only speech carries voice-experiment exposure, and the player needs it
  /// because a silence entry is a *clip* of a shared source rather than a
  /// whole file: [uri] points at the bundled silence asset and [expectedMs] is
  /// the clip length.
  final String kind;

  /// Whether completion requires this segment to have played.
  final bool isRequired;
}

enum SegmentLifecycle {
  started,

  /// The player reported the medium finished. Device-reported delivery
  /// evidence; never evidence that a person heard it.
  completed,
  failed,
}

class SegmentLifecycleEvent {
  const SegmentLifecycleEvent({
    required this.segmentId,
    required this.lifecycle,
    required this.positionMs,
    this.detail,
  });

  final String segmentId;
  final SegmentLifecycle lifecycle;
  final int positionMs;
  final String? detail;
}

enum PlaybackFaultKind { sourceUnreadable, decodeFailed, playerError }

class PlaybackFault {
  const PlaybackFault({
    required this.kind,
    required this.message,
    this.segmentId,
  });

  final PlaybackFaultKind kind;
  final String message;
  final String? segmentId;
}

/// What a platform player must do.
abstract interface class AudioPlayerPort {
  /// Load the ordered media for a run. Must not begin playing.
  Future<void> load(List<PlayableSegment> segments);

  Future<void> start();
  Future<void> pause();
  Future<void> resume();
  Future<void> stop();
  Future<void> dispose();

  /// Position within the whole loaded sequence.
  Duration get position;

  /// Total, once known. Null before the player has read the media.
  Duration? get duration;

  /// Segment transitions, from real player callbacks.
  Stream<SegmentLifecycleEvent> get lifecycle;

  Stream<PlaybackFault> get faults;

  /// True only while the platform player is actually producing output.
  bool get isPlaying;
}
