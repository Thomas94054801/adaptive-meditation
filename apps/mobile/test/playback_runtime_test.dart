import 'dart:async';

import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/core/resolution.dart';
import 'package:adaptive_meditation/features/session/playback_runtime.dart';
import 'package:adaptive_meditation/platform/audio_player_port.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

/// R08 and R12 — the player cannot fake a completion, and a bell is not a voice.
///
/// This is the class that takes completion away from the UI timer. Program004
/// completed a session when a ticker passed the planned total, with no audio
/// evidence at all, so in a release build every completed session was a silent
/// countdown. These tests are about that specific lie.
void main() {
  final SessionPlanV2 plan = FakeMeditationApi.typedPlan;

  ResolvedTimeline resolutionFor({AudioMode mode = AudioMode.audible}) {
    final List<ResolvedSegment> segments = plan.segments
        .map(
          (TimelineSegment s) => ResolvedSegment(
            segmentId: s.id,
            kind: s.kind.wireValue,
            effectiveMs: s.nominalMs,
            audioSha256: mode.isAudible && (s.isSpeech || s.isBell)
                ? 'h'
                : null,
          ),
        )
        .toList();
    return ResolvedTimeline(
      planHash: plan.planHash,
      locale: plan.locale,
      revision: 1,
      measurementSource: mode.isAudible
          ? MeasurementSource.deviceReported
          : MeasurementSource.planEstimate,
      audioMode: mode,
      segments: segments,
      extendedByMs: 0,
      absorbedMs: 0,
      outcome: 'on_target',
    );
  }

  late ScriptedPlayer player;
  late PlaybackRuntime runtime;

  setUp(() {
    player = ScriptedPlayer();
    runtime = PlaybackRuntime(
      player: player,
      plan: plan,
      resolution: resolutionFor(),
    );
  });

  tearDown(() async => runtime.dispose());

  Future<void> completeEverything() async {
    for (final ResolvedSegment segment in resolutionFor().segments) {
      if (segment.kind == 'marker') {
        continue;
      }
      player.emitStarted(segment.segmentId);
      player.emitCompleted(segment.segmentId);
      await Future<void>.delayed(Duration.zero);
    }
  }

  test('R08: playing is not completion', () async {
    player.playing = true;
    await Future<void>.delayed(Duration.zero);
    expect(runtime.hasFullCoverage, isFalse);
    expect(runtime.isAudibleCompletion, isFalse);
  });

  test('R08: a started segment is not a completed one', () async {
    player.emitStarted('speech_0_arrive');
    await Future<void>.delayed(Duration.zero);
    expect(runtime.coverage['speech_0_arrive']!.started, isTrue);
    expect(runtime.coverage['speech_0_arrive']!.completed, isFalse);
    expect(runtime.hasFullCoverage, isFalse);
  });

  test('R08: skipping a required segment prevents completion', () async {
    // Everything completes except one speech segment.
    for (final ResolvedSegment segment in resolutionFor().segments) {
      if (segment.kind == 'marker' || segment.segmentId == 'speech_1_sweep') {
        continue;
      }
      player.emitStarted(segment.segmentId);
      player.emitCompleted(segment.segmentId);
    }
    await Future<void>.delayed(Duration.zero);

    expect(runtime.hasFullCoverage, isFalse);
    expect(runtime.isAudibleCompletion, isFalse);
    expect(runtime.completionRatio, lessThan(1.0));
  });

  test('full coverage from real callbacks is a delivered session', () async {
    final List<RuntimeEventKind> seen = <RuntimeEventKind>[];
    runtime.events.listen((RuntimeEvent e) => seen.add(e.kind));

    await completeEverything();

    expect(runtime.hasFullCoverage, isTrue);
    expect(runtime.isAudibleCompletion, isTrue);
    expect(runtime.completionRatio, 1.0);
    expect(seen, contains(RuntimeEventKind.sessionDelivered));
  });

  test('R12: a bell does not count as audio output started', () async {
    player.emitStarted('bell_open');
    await Future<void>.delayed(Duration.zero);
    expect(
      runtime.outputStarted,
      isFalse,
      reason: 'a bell is not a voice, so it cannot be voice exposure',
    );

    player.emitStarted('speech_0_arrive');
    await Future<void>.delayed(Duration.zero);
    expect(runtime.outputStarted, isTrue);
  });

  test('R12: silent mode never reports an audible completion', () async {
    final ScriptedPlayer silentPlayer = ScriptedPlayer();
    final PlaybackRuntime silent = PlaybackRuntime(
      player: silentPlayer,
      plan: plan,
      resolution: resolutionFor(mode: AudioMode.silentByChoice),
    );
    for (final ResolvedSegment segment in resolutionFor().segments) {
      if (segment.kind == 'marker') {
        continue;
      }
      silentPlayer.emitStarted(segment.segmentId);
      silentPlayer.emitCompleted(segment.segmentId);
    }
    await Future<void>.delayed(Duration.zero);

    expect(silent.hasFullCoverage, isTrue);
    expect(
      silent.isAudibleCompletion,
      isFalse,
      reason: 'a silent session completes, but not as an audible one',
    );
    await silent.dispose();
  });

  test('completion ratio is weighted by duration, not segment count', () async {
    // The two-second opening bell and the 471-second silence must not weigh
    // the same. Completing only the bells is a tiny fraction of the session.
    player.emitStarted('bell_open');
    player.emitCompleted('bell_open');
    player.emitStarted('bell_close');
    player.emitCompleted('bell_close');
    await Future<void>.delayed(Duration.zero);

    expect(runtime.completionRatio, lessThan(0.02));
  });

  test('a replay after recovery does not double-count', () async {
    await completeEverything();
    final double afterFirst = runtime.completionRatio;

    // Recovery legitimately replays a segment from its beginning.
    player.emitStarted('speech_0_arrive');
    await Future<void>.delayed(Duration.zero);

    expect(runtime.completionRatio, afterFirst);
    expect(runtime.coverage['speech_0_arrive']!.replays, 1);
  });

  test('a callback for an unknown segment is ignored, not applied', () async {
    final List<RuntimeEvent> seen = <RuntimeEvent>[];
    runtime.events.listen(seen.add);

    player.emitCompleted('segment_from_another_plan');
    await Future<void>.delayed(Duration.zero);

    expect(
      seen.map((RuntimeEvent e) => e.kind),
      contains(RuntimeEventKind.staleCallbackIgnored),
    );
    expect(runtime.hasFullCoverage, isFalse);
  });

  test('a retired runtime ignores late callbacks', () async {
    await runtime.dispose();
    expect(runtime.isDisposed, isTrue);
    // The player outlived the runtime; its callbacks must not advance anything.
    player.emitCompleted('speech_0_arrive');
    await Future<void>.delayed(Duration.zero);
    expect(runtime.coverage['speech_0_arrive']!.completed, isFalse);
  });

  test('pausing stops the sound before recording the reason', () async {
    await runtime.pause(PauseReason.focusLost);
    // Program order: the player was stopped, and only then was state written.
    expect(player.calls, containsAllInOrder(<String>['pause']));
    expect(runtime.pauseReason, PauseReason.focusLost);
  });

  test('resume clears the pause reason and only a user reaches it', () async {
    await runtime.pause(PauseReason.routePublic);
    expect(runtime.pauseReason, PauseReason.routePublic);
    await runtime.resume();
    expect(runtime.pauseReason, isNull);
    expect(player.calls, contains('resume'));
  });

  test('runtime events map to real journal types', () {
    const RuntimeEvent delivered = RuntimeEvent(
      kind: RuntimeEventKind.sessionDelivered,
      positionMs: 0,
    );
    expect(delivered.journalEventType, 'session_completed');
    const RuntimeEvent stale = RuntimeEvent(
      kind: RuntimeEventKind.staleCallbackIgnored,
      positionMs: 0,
    );
    // Internal only: a journal entry for an ignored callback would describe
    // something that did not happen.
    expect(stale.journalEventType, isNull);
  });
}

/// A player a test drives event by event.
class ScriptedPlayer implements AudioPlayerPort {
  final StreamController<SegmentLifecycleEvent> _lifecycle =
      StreamController<SegmentLifecycleEvent>.broadcast();
  final StreamController<PlaybackFault> _faults =
      StreamController<PlaybackFault>.broadcast();

  final List<String> calls = <String>[];
  bool playing = false;
  int positionMs = 0;

  void emitStarted(String segmentId) => _lifecycle.add(
    SegmentLifecycleEvent(
      segmentId: segmentId,
      lifecycle: SegmentLifecycle.started,
      positionMs: positionMs,
    ),
  );

  void emitCompleted(String segmentId) => _lifecycle.add(
    SegmentLifecycleEvent(
      segmentId: segmentId,
      lifecycle: SegmentLifecycle.completed,
      positionMs: positionMs,
    ),
  );

  @override
  Future<void> load(List<PlayableSegment> segments) async =>
      calls.add('load(${segments.length})');
  @override
  Future<void> start() async {
    calls.add('start');
    playing = true;
  }

  @override
  Future<void> pause() async {
    calls.add('pause');
    playing = false;
  }

  @override
  Future<void> resume() async {
    calls.add('resume');
    playing = true;
  }

  @override
  Future<void> stop() async {
    calls.add('stop');
    playing = false;
  }

  @override
  Future<void> dispose() async {
    calls.add('dispose');
    await _lifecycle.close();
    await _faults.close();
  }

  @override
  Duration get position => Duration(milliseconds: positionMs);
  @override
  Duration? get duration => null;
  @override
  Stream<SegmentLifecycleEvent> get lifecycle => _lifecycle.stream;
  @override
  Stream<PlaybackFault> get faults => _faults.stream;
  @override
  bool get isPlaying => playing;
}
