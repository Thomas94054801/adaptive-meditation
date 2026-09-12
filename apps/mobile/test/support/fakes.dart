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

  static String _key(String letter) => letter * 64;

  /// A typed plan copied from real planner output.
  ///
  /// Produced by build_plan for body_awareness at ten minutes and transcribed
  /// verbatim, rather than hand-authored. An earlier version invented a
  /// 471,000 ms silence that no plan can actually produce, which made every
  /// test using it weaker evidence and hid the fact that the real maximum is
  /// 323,692 ms across all practices and durations.
  static final SessionPlanV2 typedPlan = SessionPlanV2(
    planHash: _key('a'),
    definitionId: _key('b'),
    practiceId: 'body_awareness',
    protocolId: 'body_awareness_v2',
    publicTitle: 'Body Awareness',
    locale: 'en-US',
    targetTotalMs: 604000,
    minimumTotalMs: 280000,
    guidanceDensity: 0.7,
    segments: <TimelineSegment>[
      const TimelineSegment(
        id: 'bell_open',
        kind: SegmentKind.bell,
        nominalMs: 2000,
        assetKey: 'bell.opening',
      ),
      TimelineSegment(
        id: 'speech_0_arrive',
        kind: SegmentKind.speech,
        nominalMs: 11077,
        text: 'For the next 10 minutes, let attention come down into the body.',
        transcript:
            'For the next 10 minutes, let attention come down into the body.',
        renderKey: _key('c'),
      ),
      const TimelineSegment(
        id: 'silence_0_arrive',
        kind: SegmentKind.silence,
        nominalMs: 33923,
        minMs: 13569,
        elastic: true,
      ),
      const TimelineSegment(
        id: 'marker_0_arrive',
        kind: SegmentKind.marker,
        nominalMs: 0,
        markerId: 'arrive',
      ),
      TimelineSegment(
        id: 'speech_1_settle',
        kind: SegmentKind.speech,
        nominalMs: 10154,
        text:
            'Scan the jaw, the shoulders and the hands. Where there is gripping, let it go.',
        transcript:
            'Scan the jaw, the shoulders and the hands. Where there is gripping, let it go.',
        renderKey: _key('d'),
      ),
      const TimelineSegment(
        id: 'silence_1_settle',
        kind: SegmentKind.silence,
        nominalMs: 94846,
        minMs: 37938,
        elastic: true,
      ),
      const TimelineSegment(
        id: 'marker_1_settle',
        kind: SegmentKind.marker,
        nominalMs: 0,
        markerId: 'settle',
      ),
      TimelineSegment(
        id: 'speech_2_sweep',
        kind: SegmentKind.speech,
        nominalMs: 9692,
        text:
            'Move attention slowly from the feet upward. Feel each part in turn.',
        transcript:
            'Move attention slowly from the feet upward. Feel each part in turn.',
        renderKey: _key('e'),
      ),
      const TimelineSegment(
        id: 'silence_2_sweep',
        kind: SegmentKind.silence,
        nominalMs: 260308,
        minMs: 104123,
        elastic: true,
      ),
      const TimelineSegment(
        id: 'marker_2_sweep',
        kind: SegmentKind.marker,
        nominalMs: 0,
        markerId: 'sweep',
      ),
      TimelineSegment(
        id: 'speech_3_rest',
        kind: SegmentKind.speech,
        nominalMs: 8769,
        text: 'Let the whole body be felt at once, as one sensation.',
        transcript: 'Let the whole body be felt at once, as one sensation.',
        renderKey: _key('f'),
      ),
      const TimelineSegment(
        id: 'silence_3_rest',
        kind: SegmentKind.silence,
        nominalMs: 104231,
        minMs: 41692,
        elastic: true,
      ),
      const TimelineSegment(
        id: 'marker_3_rest',
        kind: SegmentKind.marker,
        nominalMs: 0,
        markerId: 'rest',
      ),
      TimelineSegment(
        id: 'speech_4_close',
        kind: SegmentKind.speech,
        nominalMs: 7846,
        text: 'Notice how the body feels now compared with when you began.',
        transcript:
            'Notice how the body feels now compared with when you began.',
        renderKey: _key('g'),
      ),
      const TimelineSegment(
        id: 'silence_4_close',
        kind: SegmentKind.silence,
        nominalMs: 59154,
        minMs: 23661,
        elastic: true,
      ),
      const TimelineSegment(
        id: 'marker_4_close',
        kind: SegmentKind.marker,
        nominalMs: 0,
        markerId: 'close',
      ),
      const TimelineSegment(
        id: 'bell_close',
        kind: SegmentKind.bell,
        nominalMs: 2000,
        assetKey: 'bell.closing',
      ),
    ],
  );

  /// Whether createSession hands back a typed plan. Off by default so the
  /// existing Program001 flow tests keep exercising the stage player.
  bool withTypedPlan = false;

  final List<Map<String, dynamic>> playbackCommands = <Map<String, dynamic>>[];
  final List<Map<String, dynamic>> appendedEvents = <Map<String, dynamic>>[];
  final List<String> preparedSessions = <String>[];

  /// Returned by applyPlaybackCommand. Null means "accepted as sent".
  PlaybackState? playbackReply;

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
      planV2: withTypedPlan ? typedPlan : null,
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
  Future<RenderManifest> prepareSession(String sessionId) async {
    _maybeFail();
    preparedSessions.add(sessionId);
    // The shipping default: nothing resolved server-side, every segment spoken
    // by the device.
    return RenderManifest(
      sessionId: sessionId,
      planHash: typedPlan.planHash,
      providerId: 'none',
      entries: const <RenderManifestEntry>[],
      unresolved: typedPlan.speech
          .map((TimelineSegment s) => s.id)
          .toList(growable: false),
      complete: false,
    );
  }

  @override
  Future<PlaybackState> applyPlaybackCommand({
    required String sessionId,
    required String command,
    required String commandId,
    required int sequence,
    required int elapsedMs,
    String? segmentId,
  }) async {
    _maybeFail();
    playbackCommands.add(<String, dynamic>{
      'command': command,
      'command_id': commandId,
      'sequence': sequence,
      'elapsed_ms': elapsedMs,
      'segment_id': segmentId,
    });
    return playbackReply ??
        PlaybackState(
          sessionId: sessionId,
          runState: _stateAfter(command),
          elapsedMs: elapsedMs,
          commandSequence: sequence,
          applied: true,
          lastSegmentId: segmentId,
        );
  }

  @override
  Future<PlaybackState> playbackState(String sessionId) async {
    _maybeFail();
    return playbackReply ??
        PlaybackState(
          sessionId: sessionId,
          runState: 'created',
          elapsedMs: 0,
          commandSequence: 0,
          applied: false,
        );
  }

  @override
  Future<void> appendEvents(
    String sessionId,
    List<Map<String, dynamic>> events,
  ) async {
    _maybeFail();
    appendedEvents.addAll(events);
  }

  static String _stateAfter(String command) => switch (command) {
    'prepare' => 'preparing',
    'resolved' => 'ready',
    'start' || 'resume' => 'playing',
    'pause' || 'interrupt' || 'interruption_ended' => 'paused',
    'complete' => 'completed',
    'abandon' => 'abandoned',
    _ => 'failed',
  };

  @override
  Future<WellnessDisclaimer> disclaimer() async {
    _maybeFail();
    return const WellnessDisclaimer(
      title: 'Before you start',
      body:
          'This app supports mindfulness and general wellbeing. It is not a '
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
      'experiment_exposures': <dynamic>[],
      'playback_events': <dynamic>[],
    };
  }
}
