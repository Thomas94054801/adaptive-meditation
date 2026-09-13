import 'dart:async';

import 'package:just_audio/just_audio.dart';

import 'audio_player_port.dart';

/// `just_audio` behind [AudioPlayerPort].
///
/// Two constructor flags carry most of the design.
///
/// `handleInterruptions: false` — by default the plugin resumes playback after
/// an interruption ends. For a meditation that is exactly wrong: a voice
/// starting the instant a phone call ends. This package takes interruptions
/// over entirely, through the audio session, and the only thing that resumes
/// playback is a user action.
///
/// `handleAudioSessionActivation: false` — there must be exactly one owner of
/// session activation. `NativeAudioSession` is it. Two owners setting the
/// category and active flag is how a session ends up configured for whatever
/// happened to run last.
class NativeAudioPlayer implements AudioPlayerPort {
  NativeAudioPlayer({AudioPlayer? player})
    : _player =
          player ??
          AudioPlayer(
            handleInterruptions: false,
            handleAudioSessionActivation: false,
            // Never skip a required segment to keep playing. A run that
            // silently skipped guidance must not report completion.
            maxSkipsOnError: 0,
          );

  final AudioPlayer _player;

  final StreamController<SegmentLifecycleEvent> _lifecycle =
      StreamController<SegmentLifecycleEvent>.broadcast();
  final StreamController<PlaybackFault> _faults =
      StreamController<PlaybackFault>.broadcast();

  List<PlayableSegment> _segments = const <PlayableSegment>[];
  StreamSubscription<int?>? _indexSub;
  StreamSubscription<PlayerState>? _stateSub;
  int? _announcedIndex;
  bool _sequenceComplete = false;

  @override
  Stream<SegmentLifecycleEvent> get lifecycle => _lifecycle.stream;

  @override
  Stream<PlaybackFault> get faults => _faults.stream;

  @override
  Duration get position => _player.position;

  @override
  Duration? get duration => _player.duration;

  @override
  bool get isPlaying => _player.playing;

  @override
  Future<void> load(List<PlayableSegment> segments) async {
    _segments = List<PlayableSegment>.unmodifiable(segments);
    _announcedIndex = null;
    _sequenceComplete = false;

    final List<AudioSource> sources = segments
        .map<AudioSource>(_sourceFor)
        .toList(growable: false);

    try {
      // preload: false so a twenty-minute session is not decoded up front.
      // Every file was already decode-probed during prepare; playback needs a
      // bounded buffer, not the whole session resident as PCM.
      await _player.setAudioSources(sources, preload: false);
    } on PlayerException catch (error) {
      _faults.add(
        PlaybackFault(
          kind: PlaybackFaultKind.sourceUnreadable,
          message: 'could not load the sequence: ${error.message}',
        ),
      );
      rethrow;
    }

    // Index changes are how a sequence advances. A change is a *boundary*, not
    // a completion in itself: the segment that just ended is the one being
    // completed, and the new index is the one starting.
    _indexSub ??= _player.currentIndexStream.listen(_onIndex);
    _stateSub ??= _player.playerStateStream.listen(_onState);
  }

  /// One playlist entry per segment.
  ///
  /// Silence is a clip out of the shared bundled source rather than a file of
  /// its own. `SilenceAudioSource` would have been the obvious choice and is
  /// Android-only: just_audio's darwin decoder has no `silence` branch and
  /// returns nil, so it would work on one platform and vanish on the other.
  /// `ClippingAudioSource` over an asset is implemented on both, and because
  /// the clip is a single entry it reports started and completed through the
  /// same index handler as everything else - which is what gives silence real
  /// completion evidence instead of a timer.
  AudioSource _sourceFor(PlayableSegment segment) {
    if (segment.kind == 'silence') {
      return ClippingAudioSource(
        child: AudioSource.asset(segment.uri),
        start: Duration.zero,
        end: Duration(milliseconds: segment.expectedMs),
      );
    }
    return AudioSource.uri(Uri.parse(segment.uri));
  }

  void _onIndex(int? index) {
    if (index == null || index < 0 || index >= _segments.length) {
      return;
    }
    final int? previous = _announcedIndex;
    if (previous != null && previous != index && previous < _segments.length) {
      _emit(previous, SegmentLifecycle.completed);
    }
    if (previous != index) {
      _announcedIndex = index;
      _emit(index, SegmentLifecycle.started);
    }
  }

  void _onState(PlayerState state) {
    // `completed` on the processing state is the only signal that the whole
    // sequence finished. `playing == true`, a ready state, or a seek are not
    // completion of anything, and treating them as such is how a run reports
    // success without having played its final segment.
    if (state.processingState != ProcessingState.completed ||
        _sequenceComplete) {
      return;
    }
    _sequenceComplete = true;
    final int? last = _announcedIndex;
    if (last != null && last < _segments.length) {
      _emit(last, SegmentLifecycle.completed);
    }
  }

  void _emit(int index, SegmentLifecycle lifecycle) {
    _lifecycle.add(
      SegmentLifecycleEvent(
        segmentId: _segments[index].segmentId,
        lifecycle: lifecycle,
        positionMs: _player.position.inMilliseconds,
      ),
    );
  }

  @override
  Future<void> start() => _player.play();

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> resume() => _player.play();

  @override
  Future<void> stop() => _player.stop();

  @override
  Future<void> dispose() async {
    await _indexSub?.cancel();
    await _stateSub?.cancel();
    await _lifecycle.close();
    await _faults.close();
    await _player.dispose();
  }
}
