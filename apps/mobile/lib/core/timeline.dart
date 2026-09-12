/// Typed timeline models — the client half of the Program004 session plan.
///
/// Deliberately a separate file from [models.dart]: the v1 stage plan is still
/// the wire contract for history and feedback, and a session created before
/// typed plans existed must keep rendering. A session carries whichever it has.
library;

/// What a segment is. The set is closed; an unknown kind is a contract break.
enum SegmentKind {
  speech('speech'),
  silence('silence'),
  bell('bell'),
  marker('marker');

  const SegmentKind(this.wireValue);

  final String wireValue;

  static SegmentKind fromWire(String value) => values.firstWhere(
    (SegmentKind kind) => kind.wireValue == value,
    orElse: () => throw FormatException('unknown segment kind: $value'),
  );
}

/// One piece of a session.
///
/// A single class rather than a hierarchy because the player treats them
/// uniformly - each one occupies a window and either speaks, waits, rings or
/// marks - and a sealed hierarchy here would mean four visitors for no gain.
class TimelineSegment {
  const TimelineSegment({
    required this.id,
    required this.kind,
    required this.nominalMs,
    this.text = '',
    this.transcript = '',
    this.renderKey = '',
    this.minMs = 0,
    this.elastic = false,
    this.assetKey = '',
    this.markerId = '',
  });

  factory TimelineSegment.fromJson(Map<String, dynamic> json) {
    final SegmentKind kind = SegmentKind.fromWire(json['kind'] as String);
    switch (kind) {
      case SegmentKind.speech:
        return TimelineSegment(
          id: json['id'] as String,
          kind: kind,
          nominalMs: json['estimated_ms'] as int,
          text: json['text'] as String,
          transcript: json['transcript'] as String,
          renderKey: json['render_key'] as String,
        );
      case SegmentKind.silence:
        return TimelineSegment(
          id: json['id'] as String,
          kind: kind,
          nominalMs: json['target_ms'] as int,
          minMs: json['min_ms'] as int,
          elastic: json['elastic'] as bool? ?? true,
        );
      case SegmentKind.bell:
        return TimelineSegment(
          id: json['id'] as String,
          kind: kind,
          nominalMs: json['duration_ms'] as int,
          assetKey: json['asset_key'] as String? ?? '',
        );
      case SegmentKind.marker:
        return TimelineSegment(
          id: json['id'] as String,
          kind: kind,
          nominalMs: 0,
          markerId: json['marker_id'] as String? ?? '',
        );
    }
  }

  final String id;
  final SegmentKind kind;

  /// Planned duration. Zero for a marker, which is an instant.
  final int nominalMs;

  final String text;

  /// What a screen reader or the transcript sheet shows. Equal to [text] today;
  /// separate because a spoken form and a written form can legitimately differ.
  final String transcript;

  final String renderKey;
  final int minMs;
  final bool elastic;
  final String assetKey;
  final String markerId;

  bool get isSpeech => kind == SegmentKind.speech;
  bool get isSilence => kind == SegmentKind.silence;
  bool get isBell => kind == SegmentKind.bell;

  /// How far this segment may shrink to absorb a speech overrun.
  int get shrinkableMs => elastic ? (nominalMs - minMs).clamp(0, nominalMs) : 0;
}

/// A segment placed on the absolute timeline.
class ScheduledSegment {
  const ScheduledSegment({
    required this.index,
    required this.segment,
    required this.startMs,
    required this.endMs,
  });

  final int index;
  final TimelineSegment segment;
  final int startMs;
  final int endMs;

  int get durationMs => endMs - startMs;

  bool contains(int positionMs) => positionMs >= startMs && positionMs < endMs;
}

/// The typed plan. Mirrors SessionPlanV2 on the wire.
class SessionPlanV2 {
  SessionPlanV2({
    required this.planHash,
    required this.definitionId,
    required this.practiceId,
    required this.protocolId,
    required this.publicTitle,
    required this.locale,
    required this.targetTotalMs,
    required this.minimumTotalMs,
    required this.guidanceDensity,
    required this.segments,
  }) : schedule = _schedule(segments);

  factory SessionPlanV2.fromJson(Map<String, dynamic> json) => SessionPlanV2(
    planHash: json['plan_hash'] as String,
    definitionId: json['definition_id'] as String,
    practiceId: json['practice_id'] as String,
    protocolId: json['protocol_id'] as String,
    publicTitle: json['public_title'] as String,
    locale: json['locale'] as String,
    targetTotalMs: json['target_total_ms'] as int,
    minimumTotalMs: json['minimum_total_ms'] as int? ?? 0,
    guidanceDensity: (json['guidance_density'] as num).toDouble(),
    segments: (json['segments'] as List<dynamic>)
        .map((dynamic e) => TimelineSegment.fromJson(e as Map<String, dynamic>))
        .toList(growable: false),
  );

  final String planHash;
  final String definitionId;
  final String practiceId;
  final String protocolId;
  final String publicTitle;
  final String locale;
  final int targetTotalMs;
  final int minimumTotalMs;
  final double guidanceDensity;
  final List<TimelineSegment> segments;

  /// Absolute windows, computed once. The player asks this, not the raw list.
  final List<ScheduledSegment> schedule;

  static List<ScheduledSegment> _schedule(List<TimelineSegment> segments) {
    final List<ScheduledSegment> scheduled = <ScheduledSegment>[];
    int running = 0;
    for (int i = 0; i < segments.length; i++) {
      final TimelineSegment segment = segments[i];
      scheduled.add(
        ScheduledSegment(
          index: i,
          segment: segment,
          startMs: running,
          endMs: running + segment.nominalMs,
        ),
      );
      running += segment.nominalMs;
    }
    return List<ScheduledSegment>.unmodifiable(scheduled);
  }

  int get totalMs => schedule.isEmpty ? 0 : schedule.last.endMs;

  /// Every spoken line, in order. Silent mode and accessibility depend on it.
  List<TimelineSegment> get speech =>
      segments.where((TimelineSegment s) => s.isSpeech).toList(growable: false);

  /// The segment containing [positionMs], or null past the end.
  ///
  /// Half-open windows, matching the backend scheduler exactly: a boundary
  /// belongs to the segment starting there, so the two cannot disagree about
  /// where minute four is.
  ScheduledSegment? segmentAt(int positionMs) {
    if (positionMs < 0) {
      return null;
    }
    for (final ScheduledSegment scheduled in schedule) {
      if (scheduled.contains(positionMs)) {
        return scheduled;
      }
    }
    return null;
  }

  /// Where playback restarts after an interruption at [positionMs].
  ///
  /// Inside speech the segment restarts from its beginning: repeating up to one
  /// sentence beats joining one halfway through. Inside silence the position
  /// stands, because rewinding silence quietly lengthens the session.
  int resumePosition(int positionMs) {
    final ScheduledSegment? scheduled = segmentAt(positionMs);
    if (scheduled == null) {
      return positionMs.clamp(0, totalMs);
    }
    return scheduled.segment.isSpeech ? scheduled.startMs : positionMs;
  }

  double progressAt(int positionMs) {
    if (totalMs <= 0) {
      return 1;
    }
    return (positionMs / totalMs).clamp(0.0, 1.0);
  }
}
