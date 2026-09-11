import 'package:adaptive_meditation/app/app_scope.dart';
import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/guest.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/check_in/check_in_screen.dart';
import 'package:adaptive_meditation/features/feedback/feedback_screen.dart';
import 'package:adaptive_meditation/features/history/history_screen.dart';
import 'package:adaptive_meditation/features/history/history_store.dart';
import 'package:adaptive_meditation/features/recommendation/recommendation_screen.dart';
import 'package:adaptive_meditation/features/session/session_screen.dart';
import 'package:adaptive_meditation/features/welcome/welcome_screen.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

Widget wrap(
  Widget child, {
  required MeditationApi api,
  SessionHistoryStore? history,
  PlatformAdapters? adapters,
}) {
  final PlatformAdapters resolved = adapters ?? PlatformAdapters();
  return AppScope(
    api: api,
    guest: GuestIdentity(resolved.storage),
    history: history ?? SessionHistoryStore(),
    adapters: resolved,
    child: MaterialApp(home: child),
  );
}

/// Scrolls a lazily built list until [key] is on screen.
Future<void> scrollTo(WidgetTester tester, Key key) async {
  await tester.scrollUntilVisible(
    find.byKey(key),
    120,
    scrollable: find.byType(Scrollable).first,
  );
}

const CheckIn sampleCheckIn = CheckIn(
  goal: Goal.overthinking,
  stress: 8,
  energy: 5,
  mentalActivity: 9,
  sleepiness: 2,
  availableMinutes: 10,
  experienceLevel: ExperienceLevel.beginner,
);

void main() {
  testWidgets('welcome screen offers guest entry and no registration', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      wrap(const WelcomeScreen(), api: FakeMeditationApi()),
    );

    expect(find.text('Start a session'), findsOneWidget);
    expect(find.textContaining('No account needed'), findsOneWidget);
    expect(find.textContaining('Sign in'), findsNothing);
    expect(find.textContaining('Create account'), findsNothing);
    expect(find.textContaining('does not diagnose'), findsOneWidget);
  });

  testWidgets('check-in collects every field and submits it', (
    WidgetTester tester,
  ) async {
    final FakeMeditationApi api = FakeMeditationApi();
    await tester.pumpWidget(wrap(const CheckInScreen(), api: api));

    // The form is a ListView, so later fields are scrolled into view before
    // being asserted on; a lazy list does not build what is off screen.
    for (final String key in <String>[
      'check_in_goal',
      'scale_stress',
      'scale_energy',
      'scale_mental_activity',
      'scale_sleepiness',
      'check_in_experience',
      'check_in_submit',
    ]) {
      await scrollTo(tester, Key(key));
      expect(find.byKey(Key(key)), findsOneWidget);
    }
    for (final int minutes in availableMinutesOptions) {
      await scrollTo(tester, Key('minutes_$minutes'));
      expect(find.byKey(Key('minutes_$minutes')), findsOneWidget);
    }

    await scrollTo(tester, const Key('minutes_5'));
    await tester.tap(find.byKey(const Key('minutes_5')));
    await tester.pump();
    await scrollTo(tester, const Key('check_in_submit'));
    await tester.tap(find.byKey(const Key('check_in_submit')));
    await tester.pumpAndSettle();

    expect(api.submittedCheckIns, hasLength(1));
    expect(api.submittedCheckIns.single.availableMinutes, 5);
  });

  testWidgets('a transport failure is shown, not swallowed', (
    WidgetTester tester,
  ) async {
    final FakeMeditationApi api = FakeMeditationApi(
      failWith: const ApiException('Could not reach the service.'),
    );
    await tester.pumpWidget(wrap(const CheckInScreen(), api: api));

    await scrollTo(tester, const Key('check_in_submit'));
    await tester.tap(find.byKey(const Key('check_in_submit')));
    await tester.pumpAndSettle();

    await scrollTo(tester, const Key('check_in_error'));
    expect(find.byKey(const Key('check_in_error')), findsOneWidget);
    expect(find.textContaining('Could not reach'), findsOneWidget);
  });

  testWidgets('recommendation shows title, duration and a plain reason', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        const RecommendationScreen(
          receipt: CheckInReceipt(
            id: 'c1',
            checkIn: CheckIn(
              goal: Goal.overthinking,
              stress: 8,
              energy: 5,
              mentalActivity: 9,
              sleepiness: 2,
              availableMinutes: 10,
              experienceLevel: ExperienceLevel.beginner,
            ),
          ),
          recommendation: FakeMeditationApi.recommendation,
        ),
        api: FakeMeditationApi(),
      ),
    );

    expect(find.text('Body Awareness'), findsOneWidget);
    expect(find.text('10 minutes'), findsOneWidget);
    expect(
      find.textContaining('because your mind is busy'),
      findsOneWidget,
    );
    // Internal source mapping must never be displayed.
    expect(find.textContaining('kayanupassana'), findsNothing);
    expect(find.textContaining('body_awareness'), findsNothing);
  });

  testWidgets('session player renders the first stage, pauses and resumes', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        const SessionScreen(
          session: MeditationSession(
            id: 'session-1',
            checkInId: 'c1',
            status: 'started',
            recommendation: FakeMeditationApi.recommendation,
            plan: FakeMeditationApi.plan,
          ),
          beforeState: sampleCheckIn,
          autoStart: false,
        ),
        api: FakeMeditationApi(),
      ),
    );

    expect(find.byKey(const Key('session_progress')), findsOneWidget);
    expect(find.text('Stage 1 of 3'), findsOneWidget);
    expect(find.text('10:00'), findsOneWidget);
    expect(
      find.textContaining('Feel the points where your body meets'),
      findsOneWidget,
    );

    // Starts paused because autoStart is off, so the button offers Resume.
    expect(find.text('Resume'), findsOneWidget);
    await tester.tap(find.byKey(const Key('session_pause_resume')));
    await tester.pump();
    expect(find.text('Pause'), findsOneWidget);
    await tester.tap(find.byKey(const Key('session_pause_resume')));
    await tester.pump();
    expect(find.text('Resume'), findsOneWidget);
  });

  testWidgets('ending a session early leads to feedback', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        const SessionScreen(
          session: MeditationSession(
            id: 'session-1',
            checkInId: 'c1',
            status: 'started',
            recommendation: FakeMeditationApi.recommendation,
            plan: FakeMeditationApi.plan,
          ),
          beforeState: sampleCheckIn,
          autoStart: false,
        ),
        api: FakeMeditationApi(),
      ),
    );

    await tester.tap(find.byKey(const Key('session_end')));
    await tester.pumpAndSettle();

    expect(find.text('Session ended'), findsOneWidget);
    expect(find.byKey(const Key('feedback_after_score')), findsOneWidget);
  });

  testWidgets('feedback sends the full after-state and records history', (
    WidgetTester tester,
  ) async {
    final FakeMeditationApi api = FakeMeditationApi();
    final SessionHistoryStore history = SessionHistoryStore();
    await tester.pumpWidget(
      wrap(
        const FeedbackScreen(
          session: MeditationSession(
            id: 'session-1',
            checkInId: 'c1',
            status: 'started',
            recommendation: FakeMeditationApi.recommendation,
            plan: FakeMeditationApi.plan,
          ),
          beforeState: sampleCheckIn,
          completed: true,
          completionRatio: 0.8,
        ),
        api: api,
        history: history,
      ),
    );

    // All four scales are asked again, so the backend can compute the outcome
    // measure that matches the goal.
    for (final String key in <String>[
      'feedback_after_score',
      'feedback_energy_after',
      'feedback_mental_activity_after',
      'feedback_sleepiness_after',
    ]) {
      await scrollTo(tester, Key(key));
      expect(find.byKey(Key(key)), findsOneWidget);
    }

    await scrollTo(tester, const Key('feedback_helpfulness_5'));
    await tester.tap(find.byKey(const Key('feedback_helpfulness_5')));
    await tester.pump();
    await scrollTo(tester, const Key('feedback_notes'));
    await tester.enterText(find.byKey(const Key('feedback_notes')), 'steadier');
    await scrollTo(tester, const Key('feedback_submit'));
    await tester.tap(find.byKey(const Key('feedback_submit')));
    await tester.pumpAndSettle();

    expect(api.submittedFeedback, hasLength(1));
    final SessionFeedback sent = api.submittedFeedback.single;
    expect(sent.helpfulness, 5);
    expect(sent.completed, isTrue);
    expect(sent.beforeScore, sampleCheckIn.stress);
    expect(sent.notes, 'steadier');
    // Defaults to the check-in values, so an untouched slider still reports a
    // real number rather than a silent null.
    expect(sent.stressAfter, sampleCheckIn.stress);
    expect(sent.energyAfter, sampleCheckIn.energy);
    expect(sent.mentalActivityAfter, sampleCheckIn.mentalActivity);
    expect(sent.sleepinessAfter, sampleCheckIn.sleepiness);
    expect(sent.completionRatio, 0.8);
    expect(history.entries, hasLength(1));
    expect(history.entries.single.practiceName, 'Body Awareness');
  });

  testWidgets('history reads from the backend', (WidgetTester tester) async {
    final FakeMeditationApi api = FakeMeditationApi()
      ..history = SessionHistoryPage(
        items: <SessionHistoryItem>[
          SessionHistoryItem(
            id: 's1',
            status: 'completed',
            createdAt: DateTime(2026, 9, 11),
            practiceId: 'mindful_walking',
            publicTitle: 'Mindful Walk',
            durationMinutes: 10,
          ),
        ],
        hasMore: false,
      );

    await tester.pumpWidget(wrap(const HistoryScreen(), api: api));
    await tester.pumpAndSettle();

    expect(find.text('Mindful Walk'), findsOneWidget);
    expect(find.textContaining('10 min'), findsOneWidget);
    expect(api.historyRequests, hasLength(1));
    // No claim that this is only "this run of the app" any more.
    expect(find.textContaining('this run of the app'), findsNothing);
  });

  testWidgets('an empty history says so without promising anything', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(wrap(const HistoryScreen(), api: FakeMeditationApi()));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('history_empty')), findsOneWidget);
  });

  testWidgets('deleting data asks once, then deletes', (WidgetTester tester) async {
    final FakeMeditationApi api = FakeMeditationApi()
      ..history = SessionHistoryPage(
        items: <SessionHistoryItem>[
          SessionHistoryItem(
            id: 's1',
            status: 'completed',
            createdAt: DateTime(2026, 9, 11),
            practiceId: 'body_awareness',
            publicTitle: 'Body Awareness',
            durationMinutes: 10,
          ),
        ],
        hasMore: false,
      );

    await tester.pumpWidget(wrap(const HistoryScreen(), api: api));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('history_delete_data')));
    await tester.pumpAndSettle();

    // One confirmation step that states what is removed, and no retention
    // option arguing the user out of it.
    expect(find.byKey(const Key('delete_data_dialog')), findsOneWidget);
    expect(find.textContaining('permanently deletes'), findsOneWidget);
    expect(find.textContaining('cannot be undone'), findsOneWidget);
    expect(find.textContaining('Keep'), findsNothing);
    expect(find.byType(Checkbox), findsNothing);

    await tester.tap(find.byKey(const Key('delete_data_confirm')));
    await tester.pumpAndSettle();

    expect(api.deleteCalls, 1);
    expect(find.byKey(const Key('history_empty')), findsOneWidget);
  });

  testWidgets('cancelling the delete dialog deletes nothing', (
    WidgetTester tester,
  ) async {
    final FakeMeditationApi api = FakeMeditationApi();
    await tester.pumpWidget(wrap(const HistoryScreen(), api: api));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('history_delete_data')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('delete_data_cancel')));
    await tester.pumpAndSettle();

    expect(api.deleteCalls, 0);
  });
}
