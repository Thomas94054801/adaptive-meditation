import 'dart:io';

import 'package:adaptive_meditation/core/audio_cache.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/core/resolution.dart';
import 'package:adaptive_meditation/features/session/prepare_controller.dart';
import 'package:adaptive_meditation/platform/audio_player_port.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';
import 'support/recording_tts.dart';

/// R01, R04, R05 — full readiness, and the ways it must refuse.
void main() {
  late Directory root;
  late AudioCache cache;
  late RecordingTts tts;
  late PrepareController controller;

  final SessionPlanV2 plan = FakeMeditationApi.typedPlan;

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
    root = await Directory.systemTemp.createTemp('prepare_test');
    cache = AudioCache(root: root);
    tts = RecordingTts(outputDirectory: root);
    controller = PrepareController(
      tts: tts,
      cache: cache,
      player: FakePlayer(),
      probeDuration: (File file) async => 8200,
    );
  });

  tearDown(() async {
    await controller.dispose();
    if (root.existsSync()) {
      await root.delete(recursive: true);
    }
  });

  test('a full prepare resolves every required segment', () async {
    final PreparedSession prepared = await controller.prepare(
      plan: plan,
      bellAssets: bells(),
    );

    // One synthesis per speech segment, and no more.
    expect(tts.requests, hasLength(plan.speech.length));
    expect(prepared.resolution.audioMode, AudioMode.audible);
    expect(
      prepared.resolution.measurementSource,
      MeasurementSource.deviceReported,
    );
    // Every speech and bell segment carries an output hash.
    for (final ResolvedSegment segment in prepared.resolution.segments) {
      if (segment.kind == 'speech' || segment.kind == 'bell') {
        expect(segment.audioSha256, isNotNull, reason: segment.segmentId);
      }
    }
    // And every file is pinned before ready, so eviction cannot take the next
    // segment while the user decides whether to start.
    expect(prepared.pinnedHashes, isNotEmpty);
    for (final String hash in prepared.pinnedHashes) {
      expect(cache.isPinned(hash), isTrue);
    }
  });

  test('R01: a later segment failing means no ready at all', () async {
    // The first segment synthesises; the third does not. Program004R has one
    // readiness model, so a session that could start and then run out of audio
    // must not start.
    tts.failOnCall = 3;

    await expectLater(
      controller.prepare(plan: plan, bellAssets: bells()),
      throwsA(
        isA<PrepareRejected>().having(
          (PrepareRejected e) => e.failure,
          'failure',
          PrepareFailure.synthesisFailed,
        ),
      ),
    );
  });

  test('a device with no engine cannot reach ready', () async {
    final PrepareController noEngine = PrepareController(
      tts: const UnavailableTtsProvider(),
      cache: cache,
      player: FakePlayer(),
    );
    await expectLater(
      noEngine.prepare(plan: plan, bellAssets: bells()),
      throwsA(
        isA<PrepareRejected>().having(
          (PrepareRejected e) => e.failure,
          'failure',
          PrepareFailure.noEngine,
        ),
      ),
    );
    await noEngine.dispose();
  });

  test('a file that does not decode cannot reach ready', () async {
    final PrepareController undecodable = PrepareController(
      tts: tts,
      cache: cache,
      player: FakePlayer(),
      // The engine wrote bytes and reported success; the decoder disagrees.
      probeDuration: (File file) async => null,
    );
    await expectLater(
      undecodable.prepare(plan: plan, bellAssets: bells()),
      throwsA(
        isA<PrepareRejected>().having(
          (PrepareRejected e) => e.failure,
          'failure',
          PrepareFailure.verificationFailed,
        ),
      ),
    );
    await undecodable.dispose();
  });

  test('a bell that is not bundled cannot reach ready', () async {
    // The Program004 defect, as a test: assets present in the repository but
    // not shipped in the app.
    await expectLater(
      controller.prepare(plan: plan, bellAssets: <String, BundledAsset>{}),
      throwsA(
        isA<PrepareRejected>().having(
          (PrepareRejected e) => e.failure,
          'failure',
          PrepareFailure.verificationFailed,
        ),
      ),
    );
  });

  test('cancelling stops preparation and reports it', () async {
    final Future<PreparedSession> pending = controller.prepare(
      plan: plan,
      bellAssets: bells(),
    );
    await controller.cancel();
    await expectLater(
      pending,
      throwsA(
        isA<PrepareRejected>().having(
          (PrepareRejected e) => e.failure,
          'failure',
          PrepareFailure.cancelled,
        ),
      ),
    );
  });

  test('silent mode by choice is a complete mode, not a failure', () async {
    final PreparedSession prepared = await controller.prepare(
      plan: plan,
      bellAssets: bells(),
      mode: AudioMode.silentByChoice,
    );
    expect(prepared.resolution.audioMode, AudioMode.silentByChoice);
    expect(
      prepared.resolution.measurementSource,
      MeasurementSource.planEstimate,
    );
    // No synthesis at all, and no audio hashes claimed.
    expect(tts.requests, isEmpty);
    expect(
      prepared.resolution.segments.every(
        (ResolvedSegment s) => s.audioSha256 == null,
      ),
      isTrue,
    );
  });

  test('a measured overrun is absorbed, never below a floor', () async {
    final PrepareController slow = PrepareController(
      tts: tts,
      cache: cache,
      player: FakePlayer(),
      // Every utterance runs three seconds long.
      probeDuration: (File file) async => 12000,
    );
    final PreparedSession prepared = await slow.prepare(
      plan: plan,
      bellAssets: bells(),
    );

    expect(prepared.resolution.absorbedMs, greaterThan(0));
    for (final ResolvedSegment resolved in prepared.resolution.segments) {
      if (resolved.kind != 'silence') {
        continue;
      }
      final TimelineSegment planned = plan.segments.firstWhere(
        (TimelineSegment s) => s.id == resolved.segmentId,
      );
      expect(
        resolved.effectiveMs,
        greaterThanOrEqualTo(planned.minMs),
        reason: '${resolved.segmentId} fell below its floor',
      );
    }
    await slow.dispose();
  });

  test('progress is reported and reaches ready exactly once', () async {
    final List<PrepareProgress> seen = <PrepareProgress>[];
    controller.progress.listen(seen.add);
    await controller.prepare(plan: plan, bellAssets: bells());
    await Future<void>.delayed(Duration.zero);

    expect(seen.where((PrepareProgress p) => p.isReady), hasLength(1));
    expect(seen.last.fraction, 1.0);
  });
}

/// A player that exists but plays nothing. Enough to satisfy the readiness
/// requirement that an output adapter is available.
class FakePlayer implements AudioPlayerPort {
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
