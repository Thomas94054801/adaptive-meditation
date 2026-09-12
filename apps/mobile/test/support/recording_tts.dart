import 'dart:io';

import 'package:adaptive_meditation/platform/providers.dart';
import 'package:crypto/crypto.dart';

/// A TTS provider that writes real files and records what it was asked for.
///
/// Deliberately not a no-op: prepare's job is to verify files, so a double
/// that produces none would let every verification pass vacuously.
class RecordingTts implements TtsProvider {
  RecordingTts({required this.outputDirectory});

  final Directory outputDirectory;
  final List<SynthesisRequest> requests = <SynthesisRequest>[];

  /// Fail on the nth call, 1-based. Used to prove that a later segment failing
  /// prevents readiness entirely.
  int? failOnCall;

  @override
  bool get isSupported => true;

  @override
  TtsOfflineCapability get offlineCapability =>
      TtsOfflineCapability.localUnconfirmed;

  @override
  Future<TtsEngineDescriptor> describe() async => const TtsEngineDescriptor(
    engineId: 'recording',
    voiceId: 'test-voice',
    locale: 'en-US',
    rate: defaultSpeechRate,
    pitch: defaultPitch,
    style: 'calm',
    engineVersion: '1',
    encoding: 'wav',
  );

  @override
  Future<SynthesisResult> synthesizeToFile(SynthesisRequest request) async {
    requests.add(request);
    if (failOnCall != null && requests.length == failOnCall) {
      throw const SynthesisFailed('engine failed on this utterance');
    }
    final List<int> bytes = List<int>.filled(
      512 + request.text.length,
      request.text.length % 251,
    );
    final String digest = sha256.convert(bytes).toString();
    final File file = File(
      '${outputDirectory.path}/${request.renderKeyHint}.part.wav',
    );
    await file.writeAsBytes(bytes);
    return SynthesisResult(
      file: file,
      bytes: bytes.length,
      audioSha256: digest,
      synthesisElapsedMs: 12,
      container: 'wav',
    );
  }

  @override
  Future<void> stop() async {}
}
