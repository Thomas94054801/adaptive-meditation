/// The Dart half of the resolution contract - SDD A2.
///
/// This must produce byte-identical canonical strings to
/// `backend/app/domain/timeline/resolution.py`. Both are tested against
/// `contracts/timing_fixtures.v1.json`, so neither can drift without failing a
/// test on whichever side moved.
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';

const String resolutionCanonicalizationVersion = '1';
const String resolutionTimingPolicyVersion = '1';

/// Unit and record separators. Chosen because they cannot occur in a segment
/// id, a hash or a decimal integer, so no escaping scheme is needed - and an
/// escaping scheme is one more thing two languages can implement differently.
const String _unit = '\u001F';
const String _record = '\u001E';

/// Where a duration came from. Never inferred.
enum MeasurementSource {
  deviceReported('device_reported'),
  planEstimate('plan_estimate');

  const MeasurementSource(this.wireValue);
  final String wireValue;

  static MeasurementSource fromWire(String value) => values.firstWhere(
    (MeasurementSource s) => s.wireValue == value,
    orElse: () => throw FormatException('unknown measurement source: $value'),
  );
}

/// How a session is being delivered. Three situations, never merged.
enum AudioMode {
  /// Real audio, verified before the session started.
  audible('audible'),

  /// The user asked for text only.
  silentByChoice('silent_by_choice'),

  /// Audio was unavailable and the user was told. Not an audible completion.
  silentDegraded('silent_degraded');

  const AudioMode(this.wireValue);
  final String wireValue;

  bool get isAudible => this == audible;

  static AudioMode fromWire(String value) => values.firstWhere(
    (AudioMode m) => m.wireValue == value,
    orElse: () => throw FormatException('unknown audio mode: $value'),
  );
}

class ResolvedSegment {
  const ResolvedSegment({
    required this.segmentId,
    required this.kind,
    required this.effectiveMs,
    this.audioSha256,
  });

  factory ResolvedSegment.fromJson(Map<String, dynamic> json) =>
      ResolvedSegment(
        segmentId: json['segment_id'] as String,
        kind: json['kind'] as String,
        effectiveMs: json['effective_ms'] as int,
        audioSha256: json['audio_sha256'] as String?,
      );

  final String segmentId;
  final String kind;
  final int effectiveMs;

  /// Output fingerprint of the bytes actually produced. Null for silence and
  /// for silent mode. Distinct from the render key, which fingerprints inputs.
  final String? audioSha256;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'segment_id': segmentId,
    'kind': kind,
    'effective_ms': effectiveMs,
    // Omitted rather than null, so the two languages cannot disagree about
    // whether absent and null hash the same.
    if (audioSha256 != null) 'audio_sha256': audioSha256,
  };
}

class ResolvedTimeline {
  const ResolvedTimeline({
    required this.planHash,
    required this.locale,
    required this.revision,
    required this.measurementSource,
    required this.audioMode,
    required this.segments,
    required this.extendedByMs,
    required this.absorbedMs,
    required this.outcome,
    this.timingPolicyVersion = resolutionTimingPolicyVersion,
    this.canonicalizationVersion = resolutionCanonicalizationVersion,
  });

  factory ResolvedTimeline.fromJson(Map<String, dynamic> json) =>
      ResolvedTimeline(
        planHash: json['plan_hash'] as String,
        locale: json['locale'] as String,
        revision: json['revision'] as int,
        measurementSource: MeasurementSource.fromWire(
          json['measurement_source'] as String,
        ),
        audioMode: AudioMode.fromWire(json['audio_mode'] as String),
        segments: (json['segments'] as List<dynamic>)
            .map(
              (dynamic e) =>
                  ResolvedSegment.fromJson(e as Map<String, dynamic>),
            )
            .toList(),
        extendedByMs: json['extended_by_ms'] as int,
        absorbedMs: json['absorbed_ms'] as int,
        outcome: json['outcome'] as String,
        timingPolicyVersion: json['timing_policy_version'] as String,
        canonicalizationVersion: json['canonicalization_version'] as String,
      );

  final String planHash;
  final String locale;

  /// A rebuilt resolution is a new revision, never an edit of the old one.
  final int revision;

  final MeasurementSource measurementSource;
  final AudioMode audioMode;
  final List<ResolvedSegment> segments;
  final int extendedByMs;
  final int absorbedMs;
  final String outcome;
  final String timingPolicyVersion;
  final String canonicalizationVersion;

  int get totalMs => segments.fold<int>(
    0,
    (int sum, ResolvedSegment s) => sum + s.effectiveMs,
  );

  /// The exact string both languages hash. Field order is fixed, never
  /// alphabetical, and every duration is an integer - float formatting is
  /// precisely where two runtimes diverge.
  String canonical() {
    final String head = <String>[
      canonicalizationVersion,
      normalizeNfc(planHash),
      normalizeNfc(locale),
      '$revision',
      normalizeNfc(timingPolicyVersion),
      normalizeNfc(measurementSource.wireValue),
      normalizeNfc(audioMode.wireValue),
    ].join(_unit);

    final StringBuffer body = StringBuffer();
    for (final ResolvedSegment segment in segments) {
      body
        ..write(
          <String>[
            normalizeNfc(segment.segmentId),
            normalizeNfc(segment.kind),
            '${segment.effectiveMs}',
            segment.audioSha256 ?? '',
          ].join(_unit),
        )
        ..write(_record);
    }

    final String tail = <String>[
      '$totalMs',
      '$extendedByMs',
      '$absorbedMs',
      outcome,
    ].join(_unit);

    return '$head$_record$body$tail';
  }

  String get resolutionHash =>
      sha256.convert(utf8.encode(canonical())).toString();

  Map<String, dynamic> toJson() => <String, dynamic>{
    'canonicalization_version': canonicalizationVersion,
    'plan_hash': planHash,
    'locale': locale,
    'revision': revision,
    'timing_policy_version': timingPolicyVersion,
    'measurement_source': measurementSource.wireValue,
    'audio_mode': audioMode.wireValue,
    'segments': segments.map((ResolvedSegment s) => s.toJson()).toList(),
    'total_ms': totalMs,
    'extended_by_ms': extendedByMs,
    'absorbed_ms': absorbedMs,
    'outcome': outcome,
    'resolution_hash': resolutionHash,
  };

  ResolvedTimeline nextRevision() => ResolvedTimeline(
    planHash: planHash,
    locale: locale,
    revision: revision + 1,
    measurementSource: measurementSource,
    audioMode: audioMode,
    segments: segments,
    extendedByMs: extendedByMs,
    absorbedMs: absorbedMs,
    outcome: outcome,
    timingPolicyVersion: timingPolicyVersion,
    canonicalizationVersion: canonicalizationVersion,
  );
}

/// Canonical compositions for Latin-1 Supplement and Latin Extended-A.
///
/// Dart has no NFC normaliser in its core library, and pulling in a full
/// Unicode implementation for a product whose approved content is English is
/// not a trade worth making. This table is *derived from Python's own Unicode
/// database* by backend/scripts, so it is not hand-typed, and it covers every
/// locale this product has approved content for or plausibly will.
///
/// Text needing composition outside this range passes through unchanged. That
/// is a known limit, not an oversight: the fixture set pins it, so a future
/// locale that needs more fails a test instead of silently hashing differently
/// from the backend. Keyed by base code point, then by combining mark.
const Map<int, Map<int, int>> _compositions = <int, Map<int, int>>{
  0x0041: <int, int>{
    0x0300: 0x00C0,
    0x0301: 0x00C1,
    0x0302: 0x00C2,
    0x0303: 0x00C3,
    0x0304: 0x0100,
    0x0306: 0x0102,
    0x0308: 0x00C4,
    0x030A: 0x00C5,
    0x0328: 0x0104,
  },
  0x0043: <int, int>{
    0x0301: 0x0106,
    0x0302: 0x0108,
    0x0307: 0x010A,
    0x030C: 0x010C,
    0x0327: 0x00C7,
  },
  0x0044: <int, int>{0x030C: 0x010E},
  0x0045: <int, int>{
    0x0300: 0x00C8,
    0x0301: 0x00C9,
    0x0302: 0x00CA,
    0x0304: 0x0112,
    0x0306: 0x0114,
    0x0307: 0x0116,
    0x0308: 0x00CB,
    0x030C: 0x011A,
    0x0328: 0x0118,
  },
  0x0047: <int, int>{
    0x0302: 0x011C,
    0x0306: 0x011E,
    0x0307: 0x0120,
    0x0327: 0x0122,
  },
  0x0048: <int, int>{0x0302: 0x0124},
  0x0049: <int, int>{
    0x0300: 0x00CC,
    0x0301: 0x00CD,
    0x0302: 0x00CE,
    0x0303: 0x0128,
    0x0304: 0x012A,
    0x0306: 0x012C,
    0x0307: 0x0130,
    0x0308: 0x00CF,
    0x0328: 0x012E,
  },
  0x004A: <int, int>{0x0302: 0x0134},
  0x004B: <int, int>{0x0327: 0x0136},
  0x004C: <int, int>{0x0301: 0x0139, 0x030C: 0x013D, 0x0327: 0x013B},
  0x004E: <int, int>{
    0x0301: 0x0143,
    0x0303: 0x00D1,
    0x030C: 0x0147,
    0x0327: 0x0145,
  },
  0x004F: <int, int>{
    0x0300: 0x00D2,
    0x0301: 0x00D3,
    0x0302: 0x00D4,
    0x0303: 0x00D5,
    0x0304: 0x014C,
    0x0306: 0x014E,
    0x0308: 0x00D6,
    0x030B: 0x0150,
  },
  0x0052: <int, int>{0x0301: 0x0154, 0x030C: 0x0158, 0x0327: 0x0156},
  0x0053: <int, int>{
    0x0301: 0x015A,
    0x0302: 0x015C,
    0x030C: 0x0160,
    0x0327: 0x015E,
  },
  0x0054: <int, int>{0x030C: 0x0164, 0x0327: 0x0162},
  0x0055: <int, int>{
    0x0300: 0x00D9,
    0x0301: 0x00DA,
    0x0302: 0x00DB,
    0x0303: 0x0168,
    0x0304: 0x016A,
    0x0306: 0x016C,
    0x0308: 0x00DC,
    0x030A: 0x016E,
    0x030B: 0x0170,
    0x0328: 0x0172,
  },
  0x0057: <int, int>{0x0302: 0x0174},
  0x0059: <int, int>{0x0301: 0x00DD, 0x0302: 0x0176, 0x0308: 0x0178},
  0x005A: <int, int>{0x0301: 0x0179, 0x0307: 0x017B, 0x030C: 0x017D},
  0x0061: <int, int>{
    0x0300: 0x00E0,
    0x0301: 0x00E1,
    0x0302: 0x00E2,
    0x0303: 0x00E3,
    0x0304: 0x0101,
    0x0306: 0x0103,
    0x0308: 0x00E4,
    0x030A: 0x00E5,
    0x0328: 0x0105,
  },
  0x0063: <int, int>{
    0x0301: 0x0107,
    0x0302: 0x0109,
    0x0307: 0x010B,
    0x030C: 0x010D,
    0x0327: 0x00E7,
  },
  0x0064: <int, int>{0x030C: 0x010F},
  0x0065: <int, int>{
    0x0300: 0x00E8,
    0x0301: 0x00E9,
    0x0302: 0x00EA,
    0x0304: 0x0113,
    0x0306: 0x0115,
    0x0307: 0x0117,
    0x0308: 0x00EB,
    0x030C: 0x011B,
    0x0328: 0x0119,
  },
  0x0067: <int, int>{
    0x0302: 0x011D,
    0x0306: 0x011F,
    0x0307: 0x0121,
    0x0327: 0x0123,
  },
  0x0068: <int, int>{0x0302: 0x0125},
  0x0069: <int, int>{
    0x0300: 0x00EC,
    0x0301: 0x00ED,
    0x0302: 0x00EE,
    0x0303: 0x0129,
    0x0304: 0x012B,
    0x0306: 0x012D,
    0x0308: 0x00EF,
    0x0328: 0x012F,
  },
  0x006A: <int, int>{0x0302: 0x0135},
  0x006B: <int, int>{0x0327: 0x0137},
  0x006C: <int, int>{0x0301: 0x013A, 0x030C: 0x013E, 0x0327: 0x013C},
  0x006E: <int, int>{
    0x0301: 0x0144,
    0x0303: 0x00F1,
    0x030C: 0x0148,
    0x0327: 0x0146,
  },
  0x006F: <int, int>{
    0x0300: 0x00F2,
    0x0301: 0x00F3,
    0x0302: 0x00F4,
    0x0303: 0x00F5,
    0x0304: 0x014D,
    0x0306: 0x014F,
    0x0308: 0x00F6,
    0x030B: 0x0151,
  },
  0x0072: <int, int>{0x0301: 0x0155, 0x030C: 0x0159, 0x0327: 0x0157},
  0x0073: <int, int>{
    0x0301: 0x015B,
    0x0302: 0x015D,
    0x030C: 0x0161,
    0x0327: 0x015F,
  },
  0x0074: <int, int>{0x030C: 0x0165, 0x0327: 0x0163},
  0x0075: <int, int>{
    0x0300: 0x00F9,
    0x0301: 0x00FA,
    0x0302: 0x00FB,
    0x0303: 0x0169,
    0x0304: 0x016B,
    0x0306: 0x016D,
    0x0308: 0x00FC,
    0x030A: 0x016F,
    0x030B: 0x0171,
    0x0328: 0x0173,
  },
  0x0077: <int, int>{0x0302: 0x0175},
  0x0079: <int, int>{0x0301: 0x00FD, 0x0302: 0x0177, 0x0308: 0x00FF},
  0x007A: <int, int>{0x0301: 0x017A, 0x0307: 0x017C, 0x030C: 0x017E},
};

/// Compose decomposed sequences, for the range this product needs.
String normalizeNfc(String value) {
  // Fast path: no combining marks at all, which is every English asset.
  if (!_hasCombiningMark(value)) {
    return value;
  }
  final List<int> out = <int>[];
  final List<int> units = value.codeUnits;
  for (int i = 0; i < units.length; i++) {
    final int current = units[i];
    if (i + 1 < units.length) {
      final int next = units[i + 1];
      final int? composed = _compositions[current]?[next];
      if (composed != null) {
        out.add(composed);
        i++;
        continue;
      }
    }
    out.add(current);
  }
  return String.fromCharCodes(out);
}

bool _hasCombiningMark(String value) {
  for (final int code in value.codeUnits) {
    // Combining Diacritical Marks.
    if (code >= 0x0300 && code <= 0x036F) {
      return true;
    }
  }
  return false;
}
