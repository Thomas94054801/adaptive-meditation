import 'package:adaptive_meditation/app/app_scope.dart';
import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/check_in/check_in_screen.dart';
import 'package:adaptive_meditation/features/feedback/feedback_screen.dart';
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
}) {
  return AppScope(
    api: api,
    history: history ?? SessionHistoryStore(),
    adapters: PlatformAdapters(),
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
          beforeScore: 8,
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
          beforeScore: 8,
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

  testWidgets('feedback submits and records local history', (
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
          beforeScore: 8,
          completed: true,
        ),
        api: api,
        history: history,
      ),
    );

    await tester.tap(find.byKey(const Key('feedback_helpfulness_5')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('feedback_notes')), 'steadier');
    await tester.tap(find.byKey(const Key('feedback_submit')));
    await tester.pumpAndSettle();

    expect(api.submittedFeedback, hasLength(1));
    final SessionFeedback sent = api.submittedFeedback.single;
    expect(sent.helpfulness, 5);
    expect(sent.completed, isTrue);
    expect(sent.beforeScore, 8);
    expect(sent.notes, 'steadier');
    expect(history.entries, hasLength(1));
    expect(history.entries.single.practiceName, 'Body Awareness');
  });
}
