import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_tts/flutter_tts.dart';

import 'providers.dart';

/// Device-native synthesis to a local file.
///
/// Everything awkward about this class is the point. `flutter_tts` reports a
/// queued request the same way it reports a finished one — a `1` return value —
/// so a naive adapter treats "accepted" as "done" and hands the player an empty
/// file. This adapter waits for the engine's own completion signal, and then
/// still refuses to believe it until the file exists, is non-empty and hashes.
///
/// One synthesis runs at a time per engine, because platform TTS engines
/// serialise internally anyway and overlapping requests make completion
/// callbacks ambiguous about which request they belong to. Every async result
/// is bound to a `(requestId, generation)` pair so a cancelled or superseded
/// callback cannot mark anything ready.
class NativeTtsProvider implements TtsProvider {
  NativeTtsProvider({FlutterTts? tts, Directory? outputDirectory})
    : _tts = tts ?? FlutterTts(),
      _outputDirectory = outputDirectory;

  final FlutterTts _tts;
  Directory? _outputDirectory;

  /// Serialises synthesis. A platform engine with two requests in flight
  /// cannot tell us which one a completion handler belongs to.
  Future<void> _queue = Future<void>.value();

  /// Bumped by [cancelAll]. A result carrying an older generation is dropped.
  int _generation = 0;
  int _nextRequestId = 0;

  Completer<void>? _inFlight;
  bool _configured = false;
  TtsEngineDescriptor? _descriptor;
  TtsOfflineCapability _capability = TtsOfflineCapability.localUnconfirmed;

  @override
  bool get isSupported => true;

  @override
  TtsOfflineCapability get offlineCapability => _capability;

  /// Records the outcome of an offline probe.
  ///
  /// Deliberately a setter rather than something this class infers: a voice
  /// earns [TtsOfflineCapability.localConfirmed] by rendering with the network
  /// down, and this class cannot know whether the network was down.
  void recordProbe(TtsOfflineCapability observed) => _capability = observed;

  @override
  Future<TtsEngineDescriptor> describe() async {
    final TtsEngineDescriptor? cached = _descriptor;
    if (cached != null) {
      return cached;
    }
    await _configure();

    // Each of these is a value that changes output bytes, so each belongs in
    // the render key. A field the platform will not tell us is recorded as
    // unknown rather than guessed - a wrong version in a cache key is worse
    // than an absent one.
    var engineId = 'unknown';
    var voiceId = 'unknown';
    const engineVersion = 'unknown';
    // Asked of the platform unconditionally rather than behind a
    // Platform.isAndroid guard. The guard bought nothing - an engine that
    // cannot answer already falls through to the same default - and it made
    // this method untestable anywhere except a device.
    try {
      final dynamic reported = await _tts.getDefaultEngine;
      if (reported is String && reported.isNotEmpty) {
        engineId = reported;
      } else if (Platform.isIOS) {
        engineId = 'AVSpeechSynthesizer';
      }
    } on Exception {
      engineId = Platform.isIOS ? 'AVSpeechSynthesizer' : 'unknown';
    }
    try {
      final dynamic voice = await _tts.getDefaultVoice;
      if (voice is Map) {
        voiceId = '${voice['name'] ?? voice['identifier'] ?? 'unknown'}';
      }
    } on Exception {
      voiceId = 'unknown';
    }

    final TtsEngineDescriptor descriptor = TtsEngineDescriptor(
      engineId: engineId,
      voiceId: voiceId,
      locale: 'en-US',
      rate: defaultSpeechRate,
      pitch: defaultPitch,
      style: 'calm',
      engineVersion: engineVersion,
      encoding: Platform.isIOS ? 'caf' : 'wav',
    );
    _descriptor = descriptor;
    return descriptor;
  }

  @override
  Future<SynthesisResult> synthesizeToFile(SynthesisRequest request) {
    final int generation = _generation;
    final int requestId = _nextRequestId++;
    // Chain onto the queue so at most one synthesis is outstanding, and keep
    // the chain alive even when a request fails.
    final Future<SynthesisResult> result = _queue.then(
      (_) => _synthesize(request, requestId, generation),
    );
    _queue = result.then<void>((_) {}, onError: (Object _) {});
    return result;
  }

  Future<SynthesisResult> _synthesize(
    SynthesisRequest request,
    int requestId,
    int generation,
  ) async {
    if (generation != _generation) {
      throw SynthesisCancelled(request.renderKeyHint);
    }
    await _configure();

    final Directory directory = await _resolveOutputDirectory();
    final String extension = Platform.isIOS ? 'caf' : 'wav';
    // A recognisable temporary name: a half-written file must never be
    // mistakable for a finished one, and the format must stay readable from
    // the path even before publication.
    final String partName =
        'tts_${request.renderKeyHint}.$requestId.part.$extension';
    final File partFile = File('${directory.path}/$partName');
    if (await partFile.exists()) {
      await partFile.delete();
    }

    await _tts.setLanguage(request.locale);
    await _tts.setSpeechRate(request.rate);
    await _tts.setPitch(request.pitch);
    if (request.voiceId != null && request.voiceId != 'unknown') {
      try {
        await _tts.setVoice(<String, String>{
          'name': request.voiceId!,
          'locale': request.locale,
        });
      } on Exception {
        // A voice the engine will not accept is not fatal: the default voice
        // for the locale is still a voice, and describe() recorded which.
      }
    }

    final Completer<void> completion = Completer<void>();
    _inFlight = completion;
    _tts.setCompletionHandler(() {
      if (generation == _generation && !completion.isCompleted) {
        completion.complete();
      }
    });
    _tts.setErrorHandler((dynamic message) {
      if (generation == _generation && !completion.isCompleted) {
        completion.completeError(SynthesisFailed('$message'));
      }
    });
    _tts.setCancelHandler(() {
      if (!completion.isCompleted) {
        completion.completeError(SynthesisCancelled(request.renderKeyHint));
      }
    });

    // awaitSynthCompletion makes the platform call itself await the engine.
    // Without it the return value means "queued", and a caller that trusts it
    // hands a zero-byte file to the player.
    await _tts.awaitSynthCompletion(true);

    final Stopwatch elapsed = Stopwatch()..start();
    final dynamic accepted = await _tts.synthesizeToFile(
      request.text,
      partName,
    );
    if (accepted != 1) {
      _inFlight = null;
      throw SynthesisFailed('engine refused the request (returned $accepted)');
    }

    try {
      await completion.future.timeout(request.timeout);
    } on TimeoutException {
      _inFlight = null;
      throw SynthesisFailed(
        'engine did not report completion within ${request.timeout}',
      );
    } finally {
      elapsed.stop();
    }
    _inFlight = null;

    if (generation != _generation) {
      // Superseded while we waited. Delete the work and refuse to publish it;
      // a late result must not be able to mark a new run ready.
      if (await partFile.exists()) {
        await partFile.delete();
      }
      throw SynthesisCancelled(request.renderKeyHint);
    }

    // The engine said it finished. That is still not evidence: check the file.
    if (!await partFile.exists()) {
      throw const SynthesisFailed(
        'engine reported completion but wrote no file',
      );
    }
    final List<int> bytes = await partFile.readAsBytes();
    if (bytes.isEmpty) {
      await partFile.delete();
      throw const SynthesisFailed('engine wrote an empty file');
    }

    return SynthesisResult(
      file: partFile,
      bytes: bytes.length,
      audioSha256: sha256.convert(bytes).toString(),
      synthesisElapsedMs: elapsed.elapsedMilliseconds,
      container: extension,
    );
  }

  Future<void> _configure() async {
    if (_configured) {
      return;
    }
    // Applied once, after the plugin is loaded. The playback session category
    // is owned by the audio runtime, not here: two owners overwriting each
    // other is the failure mode this avoids.
    await _tts.awaitSpeakCompletion(true);
    _configured = true;
  }

  Future<Directory> _resolveOutputDirectory() async {
    final Directory? configured = _outputDirectory;
    if (configured != null) {
      if (!await configured.exists()) {
        await configured.create(recursive: true);
      }
      return configured;
    }
    throw StateError('NativeTtsProvider needs an output directory');
  }

  /// Point synthesis at a directory. Called once during bootstrap.
  void useOutputDirectory(Directory directory) => _outputDirectory = directory;

  /// Abandon everything in flight. Later callbacks for older generations are
  /// dropped rather than applied.
  Future<void> cancelAll() async {
    _generation += 1;
    final Completer<void>? pending = _inFlight;
    if (pending != null && !pending.isCompleted) {
      pending.completeError(const SynthesisCancelled('cancelled'));
    }
    _inFlight = null;
    try {
      await _tts.stop();
    } on Exception {
      // Stopping an engine that is not speaking is not an error worth raising.
    }
  }

  @override
  Future<void> stop() => cancelAll();
}
