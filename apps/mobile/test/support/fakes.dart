import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/models.dart';

/// In-memory API used by the widget tests. No network, no backend.
class FakeMeditationApi implements MeditationApi {
  FakeMeditationApi({this.failWith});

  /// When set, every call throws this instead of succeeding.
  final ApiException? failWith;

  final List<CheckIn> submittedCheckIns = <CheckIn>[];
  final List<String> startedSessions = <String>[];
  final List<SessionFeedback> submittedFeedback = <SessionFeedback>[];
  final List<String?> historyRequests = <String?>[];
  final List<String> exposures = <String>[];
  int createSessionCalls = 0;
  int deleteCalls = 0;
  int exportCalls = 0;
  SessionHistoryPage history = SessionHistoryPage.empty;

  static const ExperimentVariant variant = ExperimentVariant(
    experimentId: 'recommendation_explanation_copy_v1',
    variant: 'contextual',
  );

  static const Recommendation recommendation = Recommendation(
    practiceId: 'body_awareness',
    practicePublicName: 'Body Awareness',
    durationMinutes: 10,
    guidanceDensity: 0.7,
    reasonCodes: <String>[
      'goal_overthinking',
      'high_mental_activity',
      'high_stress',
    ],
    engineVersion: '2',
    ruleSetVersion: '2',
    protocolVersion: '2',
    explanationVariant: variant,
  );

  static const SessionPlan plan = SessionPlan(
    protocolId: 'body_awareness_v1',
    practiceId: 'body_awareness',
    publicTitle: 'Body Awareness',
    totalSeconds: 600,
    guidanceDensity: 0.7,
    stages: <SessionStage>[
      SessionStage(
        id: 'arrive',
        intent: 'establish_contact',
        prompt: 'Feel the points where your body meets the chair.',
        startOffsetSeconds: 0,
        durationSeconds: 60,
        guidanceCueCount: 2,
        silenceAfterSeconds: 10,
      ),
      SessionStage(
        id: 'sweep',
        intent: 'move_attention_through_body',
        prompt: 'Move attention slowly from the feet upward.',
        startOffsetSeconds: 60,
        durationSeconds: 480,
        guidanceCueCount: 8,
        silenceAfterSeconds: 40,
      ),
      SessionStage(
        id: 'close',
        intent: 'transition_out',
        prompt: 'Move your fingers before you finish.',
        startOffsetSeconds: 540,
        durationSeconds: 60,
        guidanceCueCount: 2,
        silenceAfterSeconds: 10,
      ),
    ],
  );

  void _maybeFail() {
    final ApiException? failure = failWith;
    if (failure != null) {
      throw failure;
    }
  }

  @override
  Future<Recommendation> recommend(CheckIn checkIn) async {
    _maybeFail();
    return recommendation;
  }

  @override
  Future<CheckInReceipt> submitCheckIn(CheckIn checkIn) async {
    _maybeFail();
    submittedCheckIns.add(checkIn);
    return CheckInReceipt(id: 'check-in-1', checkIn: checkIn);
  }

  @override
  Future<MeditationSession> createSession(String checkInId) async {
    _maybeFail();
    createSessionCalls++;
    return MeditationSession(
      id: 'session-1',
      checkInId: checkInId,
      status: 'created',
      recommendation: recommendation,
      plan: plan,
    );
  }

  @override
  Future<void> startSession(String sessionId) async {
    _maybeFail();
    startedSessions.add(sessionId);
  }

  @override
  Future<void> submitFeedback(
    String sessionId,
    SessionFeedback feedback,
  ) async {
    _maybeFail();
    submittedFeedback.add(feedback);
  }

  @override
  Future<SessionHistoryPage> sessionHistory({
    String? cursor,
    int limit = 20,
  }) async {
    _maybeFail();
    historyRequests.add(cursor);
    return history;
  }

  @override
  Future<void> deleteMyData() async {
    _maybeFail();
    deleteCalls++;
    history = SessionHistoryPage.empty;
  }

  @override
  Future<void> recordExposure({
    required String experimentId,
    required String context,
  }) async {
    _maybeFail();
    exposures.add('$experimentId:$context');
  }

  @override
  Future<WellnessDisclaimer> disclaimer() async {
    _maybeFail();
    return const WellnessDisclaimer(
      title: 'Before you start',
      body: 'This app supports mindfulness and general wellbeing. It is not a '
          'medical service and does not diagnose or treat any condition.',
    );
  }

  @override
  Future<Map<String, dynamic>> exportMyData() async {
    _maybeFail();
    exportCalls++;
    return <String, dynamic>{
      'guest_id': 'guest-1',
      'check_ins': <dynamic>[],
      'recommendations': <dynamic>[],
      'sessions': <dynamic>[],
      'feedback': <dynamic>[],
      'experiment_assignments': <dynamic>[],
    };
  }
}
