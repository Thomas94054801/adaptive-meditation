/// Wire models mirroring api/openapi.v1.yaml.
///
/// The client never decides which practice to run. It sends the check-in and
/// renders what the deterministic engine returns.
library;

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
    required this.recommendationVersion,
  });

  factory Recommendation.fromJson(Map<String, dynamic> json) => Recommendation(
    practiceId: json['practice_id'] as String,
    practicePublicName: json['practice_public_name'] as String,
    durationMinutes: json['duration_minutes'] as int,
    guidanceDensity: (json['guidance_density'] as num).toDouble(),
    reasonCodes: (json['reason_codes'] as List<dynamic>).cast<String>(),
    recommendationVersion: json['recommendation_version'] as String,
  );

  final String practiceId;
  final String practicePublicName;
  final int durationMinutes;
  final double guidanceDensity;
  final List<String> reasonCodes;
  final String recommendationVersion;
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

class MeditationSession {
  const MeditationSession({
    required this.id,
    required this.checkInId,
    required this.status,
    required this.recommendation,
    required this.plan,
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
      );

  final String id;
  final String checkInId;
  final String status;
  final Recommendation recommendation;
  final SessionPlan plan;
}

class SessionFeedback {
  const SessionFeedback({
    required this.afterScore,
    required this.helpfulness,
    required this.completed,
    this.beforeScore,
    this.notes,
  });

  final int afterScore;
  final int helpfulness;
  final bool completed;
  final int? beforeScore;
  final String? notes;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'after_score': afterScore,
    'helpfulness': helpfulness,
    'completed': completed,
    if (beforeScore != null) 'before_score': beforeScore,
    if (notes != null && notes!.isNotEmpty) 'notes': notes,
  };
}
