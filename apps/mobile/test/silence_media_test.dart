import 'dart:async';
import 'dart:io';

import 'package:adaptive_meditation/core/audio_cache.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/core/resolution.dart';
import 'package:adaptive_meditation/features/session/playback_runtime.dart';
import 'package:adaptive_meditation/features/session/prepare_controller.dart';
import 'package:adaptive_meditation/platform/audio_player_port.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';
import 'support/recording_tts.dart';

/// R06 — silence is real media, and completion depends on it.
///
/// Before this closeout, prepare left silence out of the playable list while
/// PlaybackRuntime still required it for coverage. The result was that
/// `isAudibleCompletion` could never become true in production, and the suite
/// did not notice because the runtime test emitted silence lifecycle events
/// itself. R06-04 and R06-09 below are written to fail on that wiring.
void main() {
  final SessionPlanV2 plan = FakeMeditationApi.typedPlan;

  late Directory root;
  late AudioCache cache;
  late RecordingTts tts;
  late PrepareController controller;

  Map<String, BundledAsset> bells() => <String, BundledAsset>{
    'bell.opening': const BundledAsset(
      assetKey: 'bell.opening',
      assetPath: 'assets/audio/bells/opening.wav',
      sha256: 'aa',
    ),
    'bell.closing': const BundledAsset(
      assetKey: 'bell.closing',
      assetPath: 'assets/audio/bells/closing.wav',
      sha256: 'bb',
    ),
  };

  setUp(() async {
    root = await Directory.systemTemp.createTemp('silence_test');
    cache = AudioCache(root: root);
    tts = RecordingTts(outputDirectory: root);
    controller = PrepareController(
      tts: tts,
      cache: cache,
      player: _InertPlayer(),
      probeDuration: (File file) async => 9000,
    );
  });

  tearDown(() async {
    await controller.dispose();
    if (root.existsSync()) {
      await root.delete(recursive: true);
    }
  });

  test(
    'R06-01: every non-zero silence becomes a real playable segment',
    () async {
      final PreparedSession prepared = await controller.prepare(
        plan: plan,
        bellAssets: bells(),
      );

      final Set<String> plannedSilence = plan.segments
          .where((TimelineSegment s) => s.isSilence && s.nominalMs > 0)
          .map((TimelineSegment s) => s.id)
          .toSet();
      final Set<String> playableSilence = prepared.playable
          .where((PlayableSegment s) => s.kind == 'silence')
          .map((PlayableSegment s) => s.segmentId)
          .toSet();

      expect(
        plannedSilence,
        isNotEmpty,
        reason: 'the fixture must contain silence',
      );
      expect(
        playableSilence,
        plannedSilence,
        reason:
            'silence used to be omitted entirely, which is the defect R06 fixes',
      );
      // And it points at the bundled source, not at a synthesised file.
      for (final PlayableSegment s in prepared.playable.where(
        (PlayableSegment s) => s.kind == 'silence',
      )) {
        expect(s.uri, bundledSilence.assetPath);
      }
    },
  );

  test(
    'R06-02: the clip length equals the resolved effective duration',
    () async {
      final PreparedSession prepared = await controller.prepare(
        plan: plan,
        bellAssets: bells(),
      );

      for (final ResolvedSegment resolved in prepared.resolution.segments) {
        if (resolved.kind != 'silence' || resolved.effectiveMs == 0) {
          continue;
        }
        final PlayableSegment entry = prepared.playable.firstWhere(
          (PlayableSegment s) => s.segmentId == resolved.segmentId,
        );
        expect(
          entry.expectedMs,
          resolved.effectiveMs,
          reason: '${resolved.segmentId} would be clipped to the wrong length',
        );
      }
    },
  );

  test(
    'R06-03: playlist order preserves plan order across all kinds',
    () async {
      final PreparedSession prepared = await controller.prepare(
        plan: plan,
        bellAssets: bells(),
      );

      // Markers are instants and carry no medium; everything else keeps its
      // place, so the playlist is the plan's audible sequence.
      final List<String> expectedOrder = plan.segments
          .where(
            (TimelineSegment s) =>
                s.isSpeech || s.isBell || (s.isSilence && s.nominalMs > 0),
          )
          .map((TimelineSegment s) => s.id)
          .toList();
      final List<String> actualOrder = prepared.playable
          .map((PlayableSegment s) => s.segmentId)
          .toList();

      expect(actualOrder, expectedOrder);
      // Specifically: a bell, then speech, then its silence.
      expect(actualOrder.first, startsWith('bell_'));
      expect(actualOrder.last, startsWith('bell_'));
    },
  );

  test(
    'R06-04: without a silence completion callback there is no audible completion',
    () async {
      // The production defect, as a test. Coverage is driven from the prepared
      // playable list, and every entry's completion is emitted - except silence
      // is deliberately withheld here, standing in for a player that never
      // received it because prepare never queued it.
      final PreparedSession prepared = await controller.prepare(
        plan: plan,
        bellAssets: bells(),
      );
      final _ScriptedPlayer player = _ScriptedPlayer();
      final PlaybackRuntime runtime = PlaybackRuntime(
        player: player,
        plan: plan,
        resolution: prepared.resolution,
      );
      await runtime.load(prepared.playable);

      for (final PlayableSegment entry in prepared.playable) {
        if (entry.kind == 'silence') {
          continue;
        }
        player.emitStarted(entry.segmentId);
        player.emitCompleted(entry.segmentId);
      }
      await Future<void>.delayed(Duration.zero);

      expect(runtime.hasFullCoverage, isFalse);
      expect(
        runtime.isAudibleCompletion,
        isFalse,
        reason: 'silence is required, so a run missing it cannot be complete',
      );
      await runtime.dispose();
    },
  );

  test('R06-09: the prepared list is sufficient for full coverage', () async {
    // The other half of R06-04, and the one that would have failed on the old
    // wiring: completing exactly what prepare queued must be enough. It used
    // not to be, because silence was required and never queued.
    final PreparedSession prepared = await controller.prepare(
      plan: plan,
      bellAssets: bells(),
    );
    final _ScriptedPlayer player = _ScriptedPlayer();
    final PlaybackRuntime runtime = PlaybackRuntime(
      player: player,
      plan: plan,
      resolution: prepared.resolution,
    );
    await runtime.load(prepared.playable);

    for (final PlayableSegment entry in prepared.playable) {
      player.emitStarted(entry.segmentId);
      player.emitCompleted(entry.segmentId);
    }
    await Future<void>.delayed(Duration.zero);

    expect(
      runtime.hasFullCoverage,
      isTrue,
      reason: 'the production mapping must queue everything coverage requires',
    );
    expect(runtime.isAudibleCompletion, isTrue);
    expect(runtime.completionRatio, 1.0);
    await runtime.dispose();
  });

  test('R06-05: an interruption during silence does not auto-resume', () async {
    final PreparedSession prepared = await controller.prepare(
      plan: plan,
      bellAssets: bells(),
    );
    final _ScriptedPlayer player = _ScriptedPlayer();
    final PlaybackRuntime runtime = PlaybackRuntime(
      player: player,
      plan: plan,
      resolution: prepared.resolution,
    );
    await runtime.load(prepared.playable);
    await runtime.start();

    final PlayableSegment silence = prepared.playable.firstWhere(
      (PlayableSegment s) => s.kind == 'silence',
    );
    player.emitStarted(silence.segmentId);
    await Future<void>.delayed(Duration.zero);

    await runtime.pause(PauseReason.focusLost);
    expect(player.isPlaying, isFalse);
    expect(runtime.pauseReason, PauseReason.focusLost);

    // Focus returning is not a user action. Nothing restarts on its own.
    expect(player.calls.where((String c) => c == 'resume'), isEmpty);
    await runtime.dispose();
  });

  test('R06-06: a silence that fails to load is not a completion', () async {
    final PreparedSession prepared = await controller.prepare(
      plan: plan,
      bellAssets: bells(),
    );
    final _ScriptedPlayer player = _ScriptedPlayer();
    final PlaybackRuntime runtime = PlaybackRuntime(
      player: player,
      plan: plan,
      resolution: prepared.resolution,
    );
    await runtime.load(prepared.playable);

    for (final PlayableSegment entry in prepared.playable) {
      if (entry.kind == 'silence') {
        player.emitFailed(entry.segmentId, 'decode failed');
        continue;
      }
      player.emitStarted(entry.segmentId);
      player.emitCompleted(entry.segmentId);
    }
    await Future<void>.delayed(Duration.zero);

    expect(runtime.hasFullCoverage, isFalse);
    expect(runtime.isAudibleCompletion, isFalse);
    await runtime.dispose();
  });

  test(
    'R06-07: silence longer than the bundled source fails prepare',
    () async {
      // 330 s of source; this plan asks for 400 s. Truncating would make a
      // different meditation, so prepare refuses.
      final SessionPlanV2 oversized = SessionPlanV2(
        planHash: 'a' * 64,
        definitionId: 'b' * 64,
        practiceId: 'body_awareness',
        protocolId: 'body_awareness_v2',
        publicTitle: 'Body Awareness',
        locale: 'en-US',
        targetTotalMs: 404000,
        minimumTotalMs: 200000,
        guidanceDensity: 0.7,
        segments: <TimelineSegment>[
          const TimelineSegment(
            id: 'bell_open',
            kind: SegmentKind.bell,
            nominalMs: 2000,
            assetKey: 'bell.opening',
          ),
          const TimelineSegment(
            id: 'silence_huge',
            kind: SegmentKind.silence,
            nominalMs: 400000,
            minMs: 160000,
            elastic: true,
          ),
          const TimelineSegment(
            id: 'bell_close',
            kind: SegmentKind.bell,
            nominalMs: 2000,
            assetKey: 'bell.closing',
          ),
        ],
      );

      await expectLater(
        controller.prepare(plan: oversized, bellAssets: bells()),
        throwsA(
          isA<PrepareRejected>()
              .having(
                (PrepareRejected e) => e.failure,
                'failure',
                PrepareFailure.verificationFailed,
              )
              .having(
                (PrepareRejected e) => e.message,
                'message',
                contains('bundled source is only'),
              ),
        ),
      );
    },
  );

  test(
    'R06-08: the bundled silence source matches its recorded provenance',
    () {
      // The generator and PROVENANCE.json are verified byte-for-byte by
      // scripts/generate_bells.py --check in CI. This pins the constant the app
      // compiles against, so the code and the manifest cannot drift.
      expect(bundledSilence.assetPath, 'assets/audio/silence/silence.wav');
      expect(bundledSilence.durationMs, 330000);
      expect(bundledSilence.sha256.length, 64);
      // 330 s x 8000 Hz x 2 bytes, mono.
      expect(330 * 8000 * 2, 5280000);
    },
  );

  test('silent mode queues no media at all', () async {
    final PreparedSession prepared = await controller.prepare(
      plan: plan,
      bellAssets: bells(),
      mode: AudioMode.silentByChoice,
    );
    expect(prepared.playable, isEmpty);
    expect(prepared.resolution.audioMode, AudioMode.silentByChoice);
  });
}

/// Exists so prepare has an output adapter. Plays nothing.
class _InertPlayer implements AudioPlayerPort {
  @override
  Future<void> load(List<PlayableSegment> segments) async {}
  @override
  Future<void> start() async {}
  @override
  Future<void> pause() async {}
  @override
  Future<void> resume() async {}
  @override
  Future<void> stop() async {}
  @override
  Future<void> dispose() async {}
  @override
  Duration get position => Duration.zero;
  @override
  Duration? get duration => null;
  @override
  Stream<SegmentLifecycleEvent> get lifecycle =>
      const Stream<SegmentLifecycleEvent>.empty();
  @override
  Stream<PlaybackFault> get faults => const Stream<PlaybackFault>.empty();
  @override
  bool get isPlaying => false;
}

/// A player a test drives event by event.
class _ScriptedPlayer implements AudioPlayerPort {
  final StreamController<SegmentLifecycleEvent> _lifecycle =
      StreamController<SegmentLifecycleEvent>.broadcast();
  final StreamController<PlaybackFault> _faults =
      StreamController<PlaybackFault>.broadcast();

  final List<String> calls = <String>[];
  bool playing = false;
  List<PlayableSegment> loaded = const <PlayableSegment>[];

  void emitStarted(String id) => _lifecycle.add(
    SegmentLifecycleEvent(
      segmentId: id,
      lifecycle: SegmentLifecycle.started,
      positionMs: 0,
    ),
  );

  void emitCompleted(String id) => _lifecycle.add(
    SegmentLifecycleEvent(
      segmentId: id,
      lifecycle: SegmentLifecycle.completed,
      positionMs: 0,
    ),
  );

  void emitFailed(String id, String detail) => _lifecycle.add(
    SegmentLifecycleEvent(
      segmentId: id,
      lifecycle: SegmentLifecycle.failed,
      positionMs: 0,
      detail: detail,
    ),
  );

  @override
  Future<void> load(List<PlayableSegment> segments) async {
    loaded = segments;
    calls.add('load(${segments.length})');
  }

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
    await _lifecycle.close();
    await _faults.close();
  }

  @override
  Duration get position => Duration.zero;
  @override
  Duration? get duration => null;
  @override
  Stream<SegmentLifecycleEvent> get lifecycle => _lifecycle.stream;
  @override
  Stream<PlaybackFault> get faults => _faults.stream;
  @override
  bool get isPlaying => playing;
}
