/// Wire models mirroring api/openapi.v1.yaml.
///
/// The client never decides which practice to run. It sends the check-in and
/// renders what the deterministic engine returns.
library;

import 'timeline.dart';

// Re-exported so a screen holding a session can name its typed plan without
// knowing which file it lives in.
export 'timeline.dart';

/// A user job. Values match the API enum exactly.
enum Goal {
  stress('stress', 'Calm stress'),
  overthinking('overthinking', 'Quiet overthinking'),
  focus('focus', 'Improve focus'),
  sleep('sleep', 'Prepare for sleep'),
  emotionalReset('emotional_reset', 'Emotional reset'),
  general('general', 'General practice');

  const Goal(this.wireValue, this.label);

  final String wireValue;
  final String label;
}

enum ExperienceLevel {
  beginner('beginner', 'New to this'),
  intermediate('intermediate', 'Some experience'),
  experienced('experienced', 'Experienced');

  const ExperienceLevel(this.wireValue, this.label);

  final String wireValue;
  final String label;
}

const List<int> availableMinutesOptions = <int>[3, 5, 10, 15, 20];

class CheckIn {
  const CheckIn({
    required this.goal,
    required this.stress,
    required this.energy,
    required this.mentalActivity,
    required this.sleepiness,
    required this.availableMinutes,
    required this.experienceLevel,
  });

  final Goal goal;
  final int stress;
  final int energy;
  final int mentalActivity;
  final int sleepiness;
  final int availableMinutes;
  final ExperienceLevel experienceLevel;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'goal': goal.wireValue,
    'stress': stress,
    'energy': energy,
    'mental_activity': mentalActivity,
    'sleepiness': sleepiness,
    'available_minutes': availableMinutes,
    'experience_level': experienceLevel.wireValue,
  };

  CheckIn copyWith({
    Goal? goal,
    int? stress,
    int? energy,
    int? mentalActivity,
    int? sleepiness,
    int? availableMinutes,
    ExperienceLevel? experienceLevel,
  }) => CheckIn(
    goal: goal ?? this.goal,
    stress: stress ?? this.stress,
    energy: energy ?? this.energy,
    mentalActivity: mentalActivity ?? this.mentalActivity,
    sleepiness: sleepiness ?? this.sleepiness,
    availableMinutes: availableMinutes ?? this.availableMinutes,
    experienceLevel: experienceLevel ?? this.experienceLevel,
  );
}

class CheckInReceipt {
  const CheckInReceipt({required this.id, required this.checkIn});

  factory CheckInReceipt.fromJson(Map<String, dynamic> json, CheckIn checkIn) =>
      CheckInReceipt(id: json['id'] as String, checkIn: checkIn);

  final String id;
  final CheckIn checkIn;
}

class Recommendation {
  const Recommendation({
    required this.practiceId,
    required this.practicePublicName,
    required this.durationMinutes,
    required this.guidanceDensity,
    required this.reasonCodes,
    required this.engineVersion,
    required this.ruleSetVersion,
    required this.protocolVersion,
    this.explanationVariant,
  });

  factory Recommendation.fromJson(Map<String, dynamic> json) => Recommendation(
    practiceId: json['practice_id'] as String,
    practicePublicName: json['practice_public_name'] as String,
    durationMinutes: json['duration_minutes'] as int,
    guidanceDensity: (json['guidance_density'] as num).toDouble(),
    reasonCodes: (json['reason_codes'] as List<dynamic>).cast<String>(),
    explanationVariant: json['explanation_variant'] == null
        ? null
        : ExperimentVariant.fromJson(
            json['explanation_variant'] as Map<String, dynamic>,
          ),
    // v2 splits the single version into three. A v1 payload is still read:
    // its recommendation_version becomes the rule set version.
    engineVersion: json['engine_version'] as String? ?? '1',
    ruleSetVersion:
        json['rule_set_version'] as String? ??
        json['recommendation_version'] as String? ??
        '1',
    protocolVersion: json['protocol_version'] as String? ?? '1',
  );

  final String practiceId;
  final String practicePublicName;
  final int durationMinutes;
  final double guidanceDensity;
  final List<String> reasonCodes;
  final String engineVersion;
  final String ruleSetVersion;
  final String protocolVersion;

  /// Presentation experiment only. It never changes [practiceId],
  /// [durationMinutes] or [guidanceDensity] - those come from the engine.
  final ExperimentVariant? explanationVariant;
}

/// The presentation variant assigned to this device for one experiment.
///
/// Receiving it is assignment. Exposure is reported separately, once the
/// variant has actually been rendered.
class ExperimentVariant {
  const ExperimentVariant({required this.experimentId, required this.variant});

  factory ExperimentVariant.fromJson(Map<String, dynamic> json) =>
      ExperimentVariant(
        experimentId: json['experiment_id'] as String,
        variant: json['variant'] as String,
      );

  final String experimentId;
  final String variant;

  bool get isContextual => variant == 'contextual';
}

class WellnessDisclaimer {
  const WellnessDisclaimer({required this.title, required this.body});

  factory WellnessDisclaimer.fromJson(Map<String, dynamic> json) =>
      WellnessDisclaimer(
        title: json['title'] as String,
        body: json['body'] as String,
      );

  final String title;
  final String body;
}

class SessionStage {
  const SessionStage({
    required this.id,
    required this.intent,
    required this.prompt,
    required this.startOffsetSeconds,
    required this.durationSeconds,
    required this.guidanceCueCount,
    required this.silenceAfterSeconds,
  });

  factory SessionStage.fromJson(Map<String, dynamic> json) => SessionStage(
    id: json['id'] as String,
    intent: json['intent'] as String,
    prompt: json['prompt'] as String,
    startOffsetSeconds: json['start_offset_seconds'] as int,
    durationSeconds: json['duration_seconds'] as int,
    guidanceCueCount: json['guidance_cue_count'] as int,
    silenceAfterSeconds: json['silence_after_seconds'] as int,
  );

  final String id;
  final String intent;
  final String prompt;
  final int startOffsetSeconds;
  final int durationSeconds;
  final int guidanceCueCount;
  final int silenceAfterSeconds;

  int get endOffsetSeconds => startOffsetSeconds + durationSeconds;
}

class SessionPlan {
  const SessionPlan({
    required this.protocolId,
    required this.practiceId,
    required this.publicTitle,
    required this.totalSeconds,
    required this.guidanceDensity,
    required this.stages,
  });

  factory SessionPlan.fromJson(Map<String, dynamic> json) => SessionPlan(
    protocolId: json['protocol_id'] as String,
    practiceId: json['practice_id'] as String,
    publicTitle: json['public_title'] as String,
    totalSeconds: json['total_seconds'] as int,
    guidanceDensity: (json['guidance_density'] as num).toDouble(),
    stages: (json['stages'] as List<dynamic>)
        .map((dynamic e) => SessionStage.fromJson(e as Map<String, dynamic>))
        .toList(growable: false),
  );

  final String protocolId;
  final String practiceId;
  final String publicTitle;
  final int totalSeconds;
  final double guidanceDensity;
  final List<SessionStage> stages;
}

/// What the backend personalized about a session, and why — Program005.
///
/// Frozen with the session. `reason` is a code the backend owns; the strings
/// a person reads are [reasonText], owned here. No score and no model output.
class Personalization {
  const Personalization({
    required this.policyVersion,
    required this.familiarityTier,
    required this.evidenceCount,
    required this.evidenceCapped,
    required this.presentationVariant,
    required this.adaptiveWordingEnabled,
    required this.personalized,
    required this.providerId,
    required this.aiAttempted,
    required this.aiAccepted,
    required this.reason,
    this.fallbackReason,
  });

  factory Personalization.fromJson(Map<String, dynamic> json) =>
      Personalization(
        policyVersion: json['personalization_policy_version'] as String,
        familiarityTier: json['familiarity_tier'] as String,
        evidenceCount: json['evidence_count'] as int,
        evidenceCapped: json['evidence_capped'] as bool,
        presentationVariant: json['presentation_variant'] as String,
        adaptiveWordingEnabled: json['adaptive_wording_enabled'] as bool,
        personalized: json['personalized'] as bool,
        providerId: json['provider_id'] as String,
        aiAttempted: json['ai_attempted'] as bool,
        aiAccepted: json['ai_accepted'] as bool,
        reason: json['reason'] as String,
        fallbackReason: json['fallback_reason'] as String?,
      );

  final String policyVersion;
  final String familiarityTier;
  final int evidenceCount;
  final bool evidenceCapped;
  final String presentationVariant;
  final bool adaptiveWordingEnabled;
  final bool personalized;
  final String providerId;
  final bool aiAttempted;
  final bool aiAccepted;
  final String reason;
  final String? fallbackReason;

  /// The one factual sentence shown to the person.
  String get reasonText => switch (reason) {
    'returning_to_this_practice' => 'Returning to this practice',
    'first_time_with_this_practice' => 'First time with this practice',
    'adaptive_wording_off' => 'Adaptive wording is off',
    'no_history_available' => 'No history available',
    _ => reason,
  };

  /// Whether generative wording was actually used. The null provider is not
  /// AI use, whatever the pipeline looked like on the way through.
  bool get usedAi => aiAttempted && aiAccepted;
}

class MeditationSession {
  const MeditationSession({
    required this.id,
    required this.checkInId,
    required this.status,
    required this.recommendation,
    required this.plan,
    this.planV2,
    this.runState = 'created',
    this.personalization,
  });

  factory MeditationSession.fromJson(Map<String, dynamic> json) =>
      MeditationSession(
        id: json['id'] as String,
        checkInId: json['check_in_id'] as String,
        status: json['status'] as String,
        recommendation: Recommendation.fromJson(
          json['recommendation'] as Map<String, dynamic>,
        ),
        plan: SessionPlan.fromJson(json['plan'] as Map<String, dynamic>),
        // Absent on sessions created before typed plans existed. Those still
        // play, on the stage timeline, which is why the v1 plan stays required.
        planV2: json['plan_v2'] == null
            ? null
            : SessionPlanV2.fromJson(json['plan_v2'] as Map<String, dynamic>),
        runState: json['run_state'] as String? ?? 'created',
        // Null before Program005: shown as not personalized, not guessed.
        personalization: json['personalization'] == null
            ? null
            : Personalization.fromJson(
                json['personalization'] as Map<String, dynamic>,
              ),
      );

  final String id;
  final String checkInId;
  final String status;
  final Recommendation recommendation;
  final SessionPlan plan;

  /// The typed timeline, when the backend produced one.
  final SessionPlanV2? planV2;

  final String runState;

  /// Program005 provenance, when the backend recorded it.
  final Personalization? personalization;

  bool get hasTypedPlan => planV2 != null;
}

/// One resolved audio file for a segment.
class RenderManifestEntry {
  const RenderManifestEntry({
    required this.segmentId,
    required this.renderKey,
    required this.durationMs,
    required this.contentSha256,
    required this.uri,
  });

  factory RenderManifestEntry.fromJson(Map<String, dynamic> json) =>
      RenderManifestEntry(
        segmentId: json['segment_id'] as String,
        renderKey: json['render_key'] as String,
        durationMs: json['duration_ms'] as int,
        contentSha256: json['content_sha256'] as String,
        uri: json['uri'] as String,
      );

  final String segmentId;
  final String renderKey;
  final int durationMs;

  /// Verified before playing. A mismatch is deleted and re-fetched, never
  /// played: a corrupt file becoming a sound in the middle of a meditation is
  /// the worst possible time to find out.
  final String contentSha256;

  final String uri;
}

/// What a session needs before it is ready to play.
class RenderManifest {
  const RenderManifest({
    required this.sessionId,
    required this.planHash,
    required this.providerId,
    required this.entries,
    required this.unresolved,
    required this.complete,
  });

  factory RenderManifest.fromJson(Map<String, dynamic> json) => RenderManifest(
    sessionId: json['session_id'] as String,
    planHash: json['plan_hash'] as String,
    providerId: json['provider_id'] as String,
    entries: (json['entries'] as List<dynamic>)
        .map(
          (dynamic e) =>
              RenderManifestEntry.fromJson(e as Map<String, dynamic>),
        )
        .toList(growable: false),
    unresolved: (json['unresolved'] as List<dynamic>).cast<String>(),
    complete: json['complete'] as bool,
  );

  final String sessionId;
  final String planHash;
  final String providerId;
  final List<RenderManifestEntry> entries;

  /// Segments the backend could not resolve. Spoken with device-native TTS, or
  /// shown as text. Not an error: with device TTS shipped first, every segment
  /// arriving unresolved is the normal case.
  final List<String> unresolved;

  final bool complete;
}

/// The backend's view of a run. Authoritative after a reconnect or a relaunch,
/// because it is the thing that survived the process dying.
class PlaybackState {
  const PlaybackState({
    required this.sessionId,
    required this.runState,
    required this.elapsedMs,
    required this.commandSequence,
    required this.applied,
    this.lastSegmentId,
    this.resumeSegmentId,
    this.resumeOffsetMs = 0,
  });

  factory PlaybackState.fromJson(Map<String, dynamic> json) => PlaybackState(
    sessionId: json['session_id'] as String,
    runState: json['run_state'] as String,
    elapsedMs: json['elapsed_ms'] as int,
    commandSequence: json['command_sequence'] as int,
    applied: json['applied'] as bool,
    lastSegmentId: json['last_segment_id'] as String?,
    resumeSegmentId: json['resume_segment_id'] as String?,
    resumeOffsetMs: json['resume_offset_ms'] as int? ?? 0,
  );

  final String sessionId;
  final String runState;
  final int elapsedMs;
  final int commandSequence;

  /// False when the command was a replay or arrived out of order. Not an error.
  final bool applied;

  final String? lastSegmentId;

  /// Where to restart. Never mid-utterance.
  final String? resumeSegmentId;
  final int resumeOffsetMs;

  bool get canResume => resumeSegmentId != null || elapsedMs > 0;
}

class SessionFeedback {
  const SessionFeedback({
    required this.afterScore,
    required this.helpfulness,
    required this.completed,
    this.beforeScore,
    this.notes,
    this.stressAfter,
    this.energyAfter,
    this.mentalActivityAfter,
    this.sleepinessAfter,
    this.completionRatio,
  });

  final int afterScore;
  final int helpfulness;
  final bool completed;
  final int? beforeScore;
  final String? notes;

  /// The full after-state, so the backend can compute the outcome measure that
  /// matches the goal. Sent together or not at all: a half-filled snapshot
  /// would give a measure for some goals and silently not for others.
  final int? stressAfter;
  final int? energyAfter;
  final int? mentalActivityAfter;
  final int? sleepinessAfter;
  final double? completionRatio;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'after_score': afterScore,
    'helpfulness': helpfulness,
    'completed': completed,
    if (beforeScore != null) 'before_score': beforeScore,
    if (notes != null && notes!.isNotEmpty) 'notes': notes,
    if (stressAfter != null) 'stress_after': stressAfter,
    if (energyAfter != null) 'energy_after': energyAfter,
    if (mentalActivityAfter != null)
      'mental_activity_after': mentalActivityAfter,
    if (sleepinessAfter != null) 'sleepiness_after': sleepinessAfter,
    if (completionRatio != null) 'completion_ratio': completionRatio,
  };
}

/// One row of the guest's server-side history.
class SessionHistoryItem {
  const SessionHistoryItem({
    required this.id,
    required this.status,
    required this.createdAt,
    required this.practiceId,
    required this.publicTitle,
    required this.durationMinutes,
  });

  factory SessionHistoryItem.fromJson(Map<String, dynamic> json) =>
      SessionHistoryItem(
        id: json['id'] as String,
        status: json['status'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        practiceId: json['practice_id'] as String,
        publicTitle: json['public_title'] as String,
        durationMinutes: json['duration_minutes'] as int,
      );

  final String id;
  final String status;
  final DateTime createdAt;
  final String practiceId;
  final String publicTitle;
  final int durationMinutes;

  bool get completed => status == 'completed';
}

class SessionHistoryPage {
  const SessionHistoryPage({
    required this.items,
    required this.hasMore,
    this.nextCursor,
  });

  factory SessionHistoryPage.fromJson(Map<String, dynamic> json) =>
      SessionHistoryPage(
        items: (json['items'] as List<dynamic>)
            .map(
              (dynamic e) =>
                  SessionHistoryItem.fromJson(e as Map<String, dynamic>),
            )
            .toList(growable: false),
        hasMore: json['has_more'] as bool,
        nextCursor: json['next_cursor'] as String?,
      );

  final List<SessionHistoryItem> items;
  final bool hasMore;
  final String? nextCursor;

  static const SessionHistoryPage empty = SessionHistoryPage(
    items: <SessionHistoryItem>[],
    hasMore: false,
  );
}
