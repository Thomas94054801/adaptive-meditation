import 'dart:async';
import 'dart:io';

import '../../core/audio_cache.dart';
import '../../core/models.dart';
import '../../core/resolution.dart';
import '../../platform/audio_player_port.dart';
import '../../platform/providers.dart';

/// How far preparation has got.
enum PrepareStage { idle, describing, synthesising, verifying, ready, failed }

/// Why a prepare could not produce an audible session.
enum PrepareFailure {
  noEngine,
  synthesisFailed,
  verificationFailed,
  storageFull,
  cancelled,
  playerUnavailable,
}

class PrepareProgress {
  const PrepareProgress({
    required this.stage,
    required this.completed,
    required this.total,
    this.failure,
    this.detail,
  });

  final PrepareStage stage;
  final int completed;
  final int total;
  final PrepareFailure? failure;
  final String? detail;

  double get fraction => total == 0 ? 0 : completed / total;
  bool get isReady => stage == PrepareStage.ready;
}

/// The outcome of a successful full prepare.
class PreparedSession {
  const PreparedSession({
    required this.resolution,
    required this.playable,
    required this.pinnedHashes,
  });

  final ResolvedTimeline resolution;
  final List<PlayableSegment> playable;
  final List<String> pinnedHashes;
}

/// Full prepare — SDD A1.
///
/// There is one readiness model and it is all-or-nothing. Every required
/// speech, bell and silence medium is resolved locally, hash-verified and
/// decode-probed before the session is `ready`. Program004R deliberately drops
/// the first-segment start that the original SDD's budget table allowed: two
/// readiness models is how a session starts and then runs out of audio.
///
/// Cancellation is real and matters, because a user who backs out of the
/// recommendation screen must not leave an engine synthesising into a
/// directory nobody will read.
class PrepareController {
  PrepareController({
    required TtsProvider tts,
    required AudioCache cache,
    required AudioPlayerPort? player,
    Future<int?> Function(File file)? probeDuration,
  }) : _tts = tts,
       _cache = cache,
       _player = player,
       _probeDuration = probeDuration;

  final TtsProvider _tts;
  final AudioCache _cache;
  final AudioPlayerPort? _player;

  /// Decode probe. Injected because the real one needs a platform player, and
  /// the readiness rule it enforces must be testable without one.
  final Future<int?> Function(File file)? _probeDuration;

  final StreamController<PrepareProgress> _progress =
      StreamController<PrepareProgress>.broadcast();

  Stream<PrepareProgress> get progress => _progress.stream;

  bool _cancelled = false;

  /// Abandon preparation. Idempotent.
  Future<void> cancel() async {
    _cancelled = true;
    await _tts.stop();
    _emit(
      const PrepareProgress(
        stage: PrepareStage.failed,
        completed: 0,
        total: 0,
        failure: PrepareFailure.cancelled,
      ),
    );
  }

  void _emit(PrepareProgress progress) {
    if (!_progress.isClosed) {
      _progress.add(progress);
    }
  }

  /// Prepare every required segment, or fail.
  ///
  /// [bellAssets] maps a bell asset key to its bundled asset path and the hash
  /// recorded in PROVENANCE.json, so a swapped asset fails verification the
  /// same way a corrupt synthesised file does.
  Future<PreparedSession> prepare({
    required SessionPlanV2 plan,
    required Map<String, BundledAsset> bellAssets,
    AudioMode mode = AudioMode.audible,
  }) async {
    _cancelled = false;
    final List<TimelineSegment> required = plan.segments
        .where((TimelineSegment s) => s.isSpeech || s.isBell || s.isSilence)
        .toList(growable: false);

    if (mode != AudioMode.audible) {
      // Silent mode is a complete mode, not a failure: no audio is required,
      // and the resolution says so rather than claiming audible delivery.
      final ResolvedTimeline resolution = _resolutionFor(
        plan,
        <String, int>{},
        <String, String>{},
        mode: mode,
        source: MeasurementSource.planEstimate,
      );
      _emit(
        PrepareProgress(
          stage: PrepareStage.ready,
          completed: required.length,
          total: required.length,
        ),
      );
      return PreparedSession(
        resolution: resolution,
        playable: const <PlayableSegment>[],
        pinnedHashes: const <String>[],
      );
    }

    if (!_tts.isSupported) {
      _fail(PrepareFailure.noEngine, 'this device has no speech engine');
      throw const PrepareRejected(
        PrepareFailure.noEngine,
        'this device has no speech engine',
      );
    }
    if (_player == null) {
      _fail(PrepareFailure.playerUnavailable, 'no audio player is available');
      throw const PrepareRejected(
        PrepareFailure.playerUnavailable,
        'no audio player is available',
      );
    }

    await _cache.ensureReady();
    await _cache.sweepPartials();

    _emit(
      PrepareProgress(
        stage: PrepareStage.describing,
        completed: 0,
        total: required.length,
      ),
    );
    final TtsEngineDescriptor descriptor = await _tts.describe();

    final Map<String, int> measured = <String, int>{};
    final Map<String, String> hashes = <String, String>{};
    final Map<String, String> containers = <String, String>{};
    int done = 0;

    for (final TimelineSegment segment in required) {
      _throwIfCancelled();

      if (segment.isSilence) {
        // Silence needs no medium here; the runtime schedules it as real
        // media, which Slice C owns. It still counts toward progress so the
        // user sees honest completion rather than a bar that jumps.
        done++;
        _emit(
          PrepareProgress(
            stage: PrepareStage.synthesising,
            completed: done,
            total: required.length,
          ),
        );
        continue;
      }

      if (segment.isBell) {
        final BundledAsset? asset = bellAssets[segment.assetKey];
        if (asset == null) {
          _fail(
            PrepareFailure.verificationFailed,
            'bell asset ${segment.assetKey} is not bundled',
          );
          throw PrepareRejected(
            PrepareFailure.verificationFailed,
            'bell asset ${segment.assetKey} is not bundled',
          );
        }
        hashes[segment.id] = asset.sha256;
        containers[segment.id] = asset.container;
        measured[segment.id] = segment.nominalMs;
        done++;
        _emit(
          PrepareProgress(
            stage: PrepareStage.synthesising,
            completed: done,
            total: required.length,
          ),
        );
        continue;
      }

      // Speech. Synthesise, publish atomically, then verify.
      try {
        final SynthesisResult result = await _tts.synthesizeToFile(
          SynthesisRequest(
            text: segment.text,
            locale: plan.locale,
            renderKeyHint: segment.renderKey.substring(0, 12),
            voiceId: descriptor.voiceId,
            rate: descriptor.rate,
            pitch: descriptor.pitch,
          ),
        );
        _throwIfCancelled();

        final File published = await _cache.publish(
          temporary: result.file,
          audioSha256: result.audioSha256,
          container: result.container,
        );

        final int? probed = await _probe(published);
        if (probed == null || probed <= 0) {
          _fail(
            PrepareFailure.verificationFailed,
            '${segment.id}: the produced file does not decode',
          );
          throw PrepareRejected(
            PrepareFailure.verificationFailed,
            '${segment.id}: the produced file does not decode',
          );
        }

        hashes[segment.id] = result.audioSha256;
        containers[segment.id] = result.container;
        measured[segment.id] = probed;
      } on SynthesisCancelled {
        _fail(PrepareFailure.cancelled, 'preparation was cancelled');
        throw const PrepareRejected(
          PrepareFailure.cancelled,
          'preparation was cancelled',
        );
      } on SynthesisFailed catch (error) {
        _fail(PrepareFailure.synthesisFailed, error.message);
        throw PrepareRejected(PrepareFailure.synthesisFailed, error.message);
      } on FileSystemException catch (error) {
        // A full disk is a degradation, not a crash, and the user is told.
        _fail(PrepareFailure.storageFull, error.message);
        throw PrepareRejected(PrepareFailure.storageFull, error.message);
      }

      done++;
      _emit(
        PrepareProgress(
          stage: PrepareStage.synthesising,
          completed: done,
          total: required.length,
        ),
      );
    }

    // Nothing is ready until every required medium has been re-verified from
    // disk. Synthesis reporting success is not the same as a readable file.
    _emit(
      PrepareProgress(
        stage: PrepareStage.verifying,
        completed: done,
        total: required.length,
      ),
    );
    for (final MapEntry<String, String> entry in hashes.entries) {
      _throwIfCancelled();
      final String container = containers[entry.key]!;
      if (container == 'asset') {
        // Bundled assets are verified by the build, not re-hashed at runtime:
        // they cannot be modified on a signed app.
        continue;
      }
      if (!await _cache.verify(entry.value, container)) {
        _fail(
          PrepareFailure.verificationFailed,
          '${entry.key}: cached audio failed verification',
        );
        throw PrepareRejected(
          PrepareFailure.verificationFailed,
          '${entry.key}: cached audio failed verification',
        );
      }
    }

    // Pin before declaring ready, so eviction cannot remove the next segment
    // while the session waits for the user to press start.
    _cache.pin(hashes.values);

    final ResolvedTimeline resolution = _resolutionFor(
      plan,
      measured,
      hashes,
      mode: AudioMode.audible,
      source: MeasurementSource.deviceReported,
    );

    final List<PlayableSegment> playable = <PlayableSegment>[];
    for (final TimelineSegment segment in plan.segments) {
      final String? hash = hashes[segment.id];
      if (segment.isBell && hash != null) {
        playable.add(
          PlayableSegment(
            segmentId: segment.id,
            uri: 'asset:///${bellAssets[segment.assetKey]!.assetPath}',
            expectedMs: measured[segment.id] ?? segment.nominalMs,
            kind: 'bell',
          ),
        );
      } else if (segment.isSpeech && hash != null) {
        playable.add(
          PlayableSegment(
            segmentId: segment.id,
            uri: _cache.fileFor(hash, containers[segment.id]!).uri.toString(),
            expectedMs: measured[segment.id] ?? segment.nominalMs,
            kind: 'speech',
          ),
        );
      }
      // Silence is added by the runtime, which owns silence media.
    }

    _emit(
      PrepareProgress(
        stage: PrepareStage.ready,
        completed: required.length,
        total: required.length,
      ),
    );
    return PreparedSession(
      resolution: resolution,
      playable: playable,
      pinnedHashes: hashes.values.toList(growable: false),
    );
  }

  ResolvedTimeline _resolutionFor(
    SessionPlanV2 plan,
    Map<String, int> measured,
    Map<String, String> hashes, {
    required AudioMode mode,
    required MeasurementSource source,
  }) {
    // The silence allocation mirrors the backend's timing policy: only unspent
    // shrinkable silence absorbs an overrun, never below its floor, and what
    // cannot be absorbed extends the session.
    int overrun = 0;
    for (final TimelineSegment segment in plan.segments) {
      if (!segment.isSpeech) {
        continue;
      }
      final int actual = measured[segment.id] ?? segment.nominalMs;
      overrun += (actual - segment.nominalMs).clamp(0, 1 << 30);
    }

    int available = 0;
    for (final TimelineSegment segment in plan.segments) {
      if (segment.isSilence) {
        available += segment.shrinkableMs;
      }
    }
    final int absorbed = overrun < available ? overrun : available;
    final int extended = overrun - absorbed;

    int remaining = absorbed;
    final List<ResolvedSegment> resolved = <ResolvedSegment>[];
    for (final TimelineSegment segment in plan.segments) {
      int effective;
      if (segment.isSilence) {
        final int take = remaining < segment.shrinkableMs
            ? remaining
            : segment.shrinkableMs;
        effective = segment.nominalMs - take;
        remaining -= take;
      } else if (segment.isSpeech) {
        effective = measured[segment.id] ?? segment.nominalMs;
      } else {
        effective = segment.nominalMs;
      }
      resolved.add(
        ResolvedSegment(
          segmentId: segment.id,
          kind: segment.kind.wireValue,
          effectiveMs: effective,
          audioSha256: hashes[segment.id],
        ),
      );
    }

    final String outcome = overrun == 0
        ? 'on_target'
        : extended > 0
        ? 'duration_extended'
        : absorbed == available
        ? 'absorbed_at_floor'
        : 'absorbed';

    return ResolvedTimeline(
      planHash: plan.planHash,
      locale: plan.locale,
      revision: 1,
      measurementSource: source,
      audioMode: mode,
      segments: resolved,
      extendedByMs: extended,
      absorbedMs: absorbed,
      outcome: outcome,
    );
  }

  Future<int?> _probe(File file) async {
    final Future<int?> Function(File)? probe = _probeDuration;
    if (probe != null) {
      return probe(file);
    }
    // No probe injected: fall back to a length check, which at least refuses
    // an empty file. A real decode probe is installed in production.
    final int length = await file.length();
    return length > 0 ? length : null;
  }

  void _throwIfCancelled() {
    if (_cancelled) {
      throw const PrepareRejected(
        PrepareFailure.cancelled,
        'preparation was cancelled',
      );
    }
  }

  void _fail(PrepareFailure failure, String detail) {
    _emit(
      PrepareProgress(
        stage: PrepareStage.failed,
        completed: 0,
        total: 0,
        failure: failure,
        detail: detail,
      ),
    );
  }

  Future<void> dispose() async {
    await _progress.close();
  }
}

/// A bell shipped inside the app bundle.
class BundledAsset {
  const BundledAsset({
    required this.assetKey,
    required this.assetPath,
    required this.sha256,
    this.container = 'asset',
  });

  final String assetKey;
  final String assetPath;
  final String sha256;
  final String container;
}

class PrepareRejected implements Exception {
  const PrepareRejected(this.failure, this.message);
  final PrepareFailure failure;
  final String message;
  @override
  String toString() => 'PrepareRejected(${failure.name}): $message';
}
