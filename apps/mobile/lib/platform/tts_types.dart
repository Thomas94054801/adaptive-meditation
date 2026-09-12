import 'dart:io';

/// Values that change synthesised bytes, and therefore belong in a cache key.
///
/// A field the platform will not report is recorded as `unknown` rather than
/// guessed: an absent version in a key is honest, a wrong one silently serves
/// the wrong audio after an OS update.
class TtsEngineDescriptor {
  const TtsEngineDescriptor({
    required this.engineId,
    required this.voiceId,
    required this.locale,
    required this.rate,
    required this.pitch,
    required this.style,
    required this.engineVersion,
    required this.encoding,
  });

  final String engineId;
  final String voiceId;
  final String locale;
  final double rate;
  final double pitch;
  final String style;
  final String engineVersion;

  /// Real container, not a guess: iOS writes CAF, Android writes WAV.
  final String encoding;

  /// The provider identity that goes into a render key.
  String get providerId => 'native:$engineId';

  /// The provider version that goes into a render key. Includes the voice and
  /// the prosody settings, because all three change the bytes.
  String get providerVersion =>
      '$engineVersion|$voiceId|${rate.toStringAsFixed(2)}|${pitch.toStringAsFixed(2)}|$style|$encoding';

  Map<String, dynamic> toJson() => <String, dynamic>{
    'engine_id': engineId,
    'voice_id': voiceId,
    'locale': locale,
    'rate': rate,
    'pitch': pitch,
    'style': style,
    'engine_version': engineVersion,
    'encoding': encoding,
  };
}

const double defaultSpeechRate = 0.44;
const double defaultPitch = 1.0;

/// One synthesis request. Product-authored text and voice settings only.
class SynthesisRequest {
  const SynthesisRequest({
    required this.text,
    required this.locale,
    required this.renderKeyHint,
    this.voiceId,
    this.rate = defaultSpeechRate,
    this.pitch = defaultPitch,
    this.timeout = const Duration(seconds: 30),
  });

  final String text;
  final String locale;

  /// Used only to name the temporary file, so a stuck request is identifiable
  /// on disk. Never sent anywhere.
  final String renderKeyHint;

  final String? voiceId;
  final double rate;
  final double pitch;

  /// An engine that never reports completion must not hang prepare forever.
  final Duration timeout;
}

/// A produced file, with the two things the caller cannot take on trust.
class SynthesisResult {
  const SynthesisResult({
    required this.file,
    required this.bytes,
    required this.audioSha256,
    required this.synthesisElapsedMs,
    required this.container,
  });

  final File file;
  final int bytes;

  /// Hash of the actual bytes. The output fingerprint, distinct from the
  /// render key, which fingerprints the inputs.
  final String audioSha256;

  /// How long synthesis took. A prepare-cost metric; never part of session
  /// duration.
  final int synthesisElapsedMs;

  final String container;
}

class SynthesisFailed implements Exception {
  const SynthesisFailed(this.message);
  final String message;
  @override
  String toString() => 'SynthesisFailed: $message';
}

class SynthesisCancelled implements Exception {
  const SynthesisCancelled(this.renderKeyHint);
  final String renderKeyHint;
  @override
  String toString() => 'SynthesisCancelled: $renderKeyHint';
}
