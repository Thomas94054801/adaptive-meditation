import 'dart:async';

import '../../core/models.dart';
import '../../core/resolution.dart';
import '../../platform/audio_player_port.dart';

/// Coverage of one required segment, from real player events.
class SegmentCoverage {
  const SegmentCoverage({
    required this.segmentId,
    required this.kind,
    required this.requiredMs,
    required this.started,
    required this.completed,
    this.replays = 0,
  });

  final String segmentId;
  final String kind;
  final int requiredMs;
  final bool started;

  /// The player reported this medium finished. Device-reported delivery
  /// evidence — never evidence that a person heard it.
  final bool completed;

  /// A legitimate replay after recovery. Recorded, and deliberately not
  /// counted twice toward completion.
  final int replays;

  SegmentCoverage copyWith({bool? started, bool? completed, int? replays}) =>
      SegmentCoverage(
        segmentId: segmentId,
        kind: kind,
        requiredMs: requiredMs,
        started: started ?? this.started,
        completed: completed ?? this.completed,
        replays: replays ?? this.replays,
      );
}

/// Why a run is paused. Replaces a separate `interrupted` state.
enum PauseReason {
  user('user'),
  focusLost('focus_lost'),
  routePublic('route_public'),
  system('system');

  const PauseReason(this.wireValue);
  final String wireValue;
}

/// The segment-lifecycle authority — SDD A4 and A7.
///
/// This is the class that takes completion away from the UI timer. Program004
/// completed a session when a 200 ms ticker passed the planned total, with no
/// audio evidence of any kind, which in a release build meant every completed
/// session was a silent countdown.
///
/// Here, completion requires every required segment to have reported
/// completion from a real player callback, plus the final medium finishing.
/// `playing == true`, a ready callback, a seek, or a playlist index change are
/// none of them completion.
class PlaybackRuntime {
  PlaybackRuntime({
    required AudioPlayerPort player,
    required this.plan,
    required this.resolution,
  }) : _player = player {
    for (final ResolvedSegment segment in resolution.segments) {
      if (segment.kind == 'marker') {
        continue;
      }
      _coverage[segment.segmentId] = SegmentCoverage(
        segmentId: segment.segmentId,
        kind: segment.kind,
        requiredMs: segment.effectiveMs,
        started: false,
        completed: false,
      );
    }
    _lifecycleSub = _player.lifecycle.listen(_onLifecycle);
    _faultSub = _player.faults.listen(_onFault);
  }

  final AudioPlayerPort _player;
  final SessionPlanV2 plan;
  final ResolvedTimeline resolution;

  final Map<String, SegmentCoverage> _coverage = <String, SegmentCoverage>{};
  final StreamController<RuntimeEvent> _events =
      StreamController<RuntimeEvent>.broadcast();

  StreamSubscription<SegmentLifecycleEvent>? _lifecycleSub;
  StreamSubscription<PlaybackFault>? _faultSub;

  /// Retired runs ignore everything. A player can outlive the runtime that
  /// was driving it, and a callback arriving afterwards must not advance a new
  /// run's coverage.
  bool _disposed = false;

  String? _currentSegmentId;
  bool _outputStarted = false;
  PauseReason? _pauseReason;
  bool _finished = false;

  Stream<RuntimeEvent> get events => _events.stream;

  /// The first moment real audio output was observed. This, not
  /// `session_started`, is what a voice experiment's exposure waits for.
  bool get outputStarted => _outputStarted;

  PauseReason? get pauseReason => _pauseReason;

  String? get currentSegmentId => _currentSegmentId;

  Map<String, SegmentCoverage> get coverage =>
      Map<String, SegmentCoverage>.unmodifiable(_coverage);

  /// Segments whose completion is required for an audible completion.
  Iterable<SegmentCoverage> get _required => _coverage.values.where(
    (SegmentCoverage c) => c.kind != 'silence' || c.requiredMs > 0,
  );

  /// Whether every required segment has real completion evidence.
  bool get hasFullCoverage =>
      _required.every((SegmentCoverage c) => c.completed);

  /// Non-overlapping covered duration over resolved required duration.
  ///
  /// Weighted by duration, not by segment count: counting segments would let a
  /// one-second bell weigh the same as an eight-minute silence. A replay after
  /// recovery is not added twice.
  double get completionRatio {
    final int total = _required.fold<int>(
      0,
      (int sum, SegmentCoverage c) => sum + c.requiredMs,
    );
    if (total == 0) {
      return 0;
    }
    final int covered = _required
        .where((SegmentCoverage c) => c.completed)
        .fold<int>(0, (int sum, SegmentCoverage c) => sum + c.requiredMs);
    return (covered / total).clamp(0.0, 1.0);
  }

  /// Hand the player the media prepare produced.
  ///
  /// Takes the list rather than deriving it: prepare already resolved every
  /// URI and verified it, and recomputing here would be a second source of
  /// truth for which file plays.
  Future<void> load(List<PlayableSegment> playable) async {
    await _player.load(playable);
  }

  void _onLifecycle(SegmentLifecycleEvent event) {
    // Only a retired runtime ignores events outright. A delivered run still
    // records what happens afterwards - a replay after recovery is a fact -
    // it simply cannot be delivered twice or add to completion again.
    if (_disposed) {
      return;
    }
    final SegmentCoverage? existing = _coverage[event.segmentId];
    if (existing == null) {
      // A callback for a segment this run does not contain: an old player, or
      // a plan that changed underneath. Never advance on it.
      _emit(
        RuntimeEvent(
          kind: RuntimeEventKind.staleCallbackIgnored,
          segmentId: event.segmentId,
          positionMs: event.positionMs,
        ),
      );
      return;
    }

    switch (event.lifecycle) {
      case SegmentLifecycle.started:
        _currentSegmentId = event.segmentId;
        final bool isReplay = existing.completed;
        _coverage[event.segmentId] = existing.copyWith(
          started: true,
          replays: isReplay ? existing.replays + 1 : existing.replays,
        );
        if (!_outputStarted && existing.kind == 'speech') {
          // Output evidence is speech playing, not a bell and not the player
          // being ready. A bell is not a voice.
          _outputStarted = true;
          _emit(
            RuntimeEvent(
              kind: RuntimeEventKind.audioOutputStarted,
              segmentId: event.segmentId,
              positionMs: event.positionMs,
            ),
          );
        }
        _emit(
          RuntimeEvent(
            kind: isReplay
                ? RuntimeEventKind.segmentReplayed
                : RuntimeEventKind.segmentStarted,
            segmentId: event.segmentId,
            positionMs: event.positionMs,
          ),
        );
      case SegmentLifecycle.completed:
        _coverage[event.segmentId] = existing.copyWith(completed: true);
        _emit(
          RuntimeEvent(
            kind: RuntimeEventKind.segmentCompleted,
            segmentId: event.segmentId,
            positionMs: event.positionMs,
          ),
        );
        if (hasFullCoverage && !_finished) {
          _finished = true;
          _emit(
            RuntimeEvent(
              kind: RuntimeEventKind.sessionDelivered,
              segmentId: event.segmentId,
              positionMs: event.positionMs,
            ),
          );
        }
      case SegmentLifecycle.failed:
        _emit(
          RuntimeEvent(
            kind: RuntimeEventKind.segmentFailed,
            segmentId: event.segmentId,
            positionMs: event.positionMs,
            detail: event.detail,
          ),
        );
    }
  }

  void _onFault(PlaybackFault fault) {
    _emit(
      RuntimeEvent(
        kind: RuntimeEventKind.playbackFault,
        segmentId: fault.segmentId,
        positionMs: _player.position.inMilliseconds,
        detail: fault.message,
      ),
    );
  }

  void _emit(RuntimeEvent event) {
    if (!_events.isClosed) {
      _events.add(event);
    }
  }

  Future<void> start() async {
    _pauseReason = null;
    await _player.start();
  }

  /// Stop sound first, then record. On focus loss or a route that would make
  /// audio audible to the room, nothing is written before the sound stops.
  Future<void> pause(PauseReason reason) async {
    await _player.pause();
    _pauseReason = reason;
    _emit(
      RuntimeEvent(
        kind: RuntimeEventKind.paused,
        segmentId: _currentSegmentId,
        positionMs: _player.position.inMilliseconds,
        detail: reason.wireValue,
      ),
    );
  }

  /// Resume. Only a user action reaches here — focus returning never does.
  Future<void> resume() async {
    _pauseReason = null;
    await _player.resume();
  }

  Future<void> stop() async {
    await _player.stop();
  }

  /// Whether this run may be reported as an audible completion.
  ///
  /// Requires full coverage from real player events **and** an audible mode.
  /// A silent-mode session completes, but not as an audible one.
  bool get isAudibleCompletion =>
      hasFullCoverage && resolution.audioMode.isAudible && _outputStarted;

  /// Whether this runtime has been retired.
  bool get isDisposed => _disposed;

  /// Retire this run so late callbacks cannot advance a new one.
  Future<void> dispose() async {
    _disposed = true;
    await _lifecycleSub?.cancel();
    await _faultSub?.cancel();
    await _events.close();
  }
}

enum RuntimeEventKind {
  segmentStarted,
  segmentCompleted,
  segmentReplayed,
  segmentFailed,
  audioOutputStarted,
  sessionDelivered,
  paused,
  playbackFault,
  staleCallbackIgnored,
}

class RuntimeEvent {
  const RuntimeEvent({
    required this.kind,
    required this.positionMs,
    this.segmentId,
    this.detail,
  });

  final RuntimeEventKind kind;
  final int positionMs;
  final String? segmentId;
  final String? detail;

  /// The journal event type this maps to, or null when it is internal.
  String? get journalEventType => switch (kind) {
    RuntimeEventKind.segmentStarted => 'segment_started',
    RuntimeEventKind.segmentCompleted => 'segment_completed',
    RuntimeEventKind.segmentReplayed => 'segment_started',
    RuntimeEventKind.segmentFailed => 'playback_failed',
    RuntimeEventKind.audioOutputStarted => 'session_started',
    RuntimeEventKind.sessionDelivered => 'session_completed',
    RuntimeEventKind.paused => 'playback_paused',
    RuntimeEventKind.playbackFault => 'playback_failed',
    RuntimeEventKind.staleCallbackIgnored => null,
  };
}
