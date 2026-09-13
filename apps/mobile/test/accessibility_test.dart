import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/check_in/check_in_screen.dart';
import 'package:adaptive_meditation/features/session/session_screen.dart';
import 'package:adaptive_meditation/features/welcome/welcome_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';
import 'support/harness.dart';

/// Accessibility baseline.
///
/// These are the guidelines Flutter can check automatically: minimum tap target
/// size, text contrast, and the presence of labels a screen reader can read.
/// Passing them is a floor, not a WCAG conformance claim - traversal order,
/// real VoiceOver and TalkBack behaviour and reduced-motion handling still need
/// a person on a device, and are recorded as manual checks in
/// docs/PROGRAM003_STATUS.md.
void main() {
  testWidgets('welcome screen meets the automated guidelines', (
    WidgetTester tester,
  ) async {
    final SemanticsHandle handle = tester.ensureSemantics();
    await tester.pumpWidget(
      wrap(const WelcomeScreen(), api: FakeMeditationApi()),
    );

    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(iOSTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    handle.dispose();
  });

  testWidgets('check-in screen meets the automated guidelines', (
    WidgetTester tester,
  ) async {
    final SemanticsHandle handle = tester.ensureSemantics();
    await tester.pumpWidget(
      wrap(const CheckInScreen(), api: FakeMeditationApi()),
    );

    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    handle.dispose();
  });

  testWidgets('session player meets the automated guidelines', (
    WidgetTester tester,
  ) async {
    final SemanticsHandle handle = tester.ensureSemantics();
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

    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    handle.dispose();
  });

  testWidgets('the wellness disclaimer appears once, on one surface', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      wrap(const WelcomeScreen(), api: FakeMeditationApi()),
    );
    expect(find.byKey(const Key('welcome_disclaimer')), findsOneWidget);
    expect(find.textContaining('does not diagnose'), findsOneWidget);
    expect(find.textContaining('cannot help in an emergency'), findsOneWidget);
  });

  testWidgets('the session player survives large text', (
    WidgetTester tester,
  ) async {
    // Dynamic Type at its practical maximum. The player must still lay out
    // rather than overflow, because the prompt is the entire point of it.
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
        child: wrap(
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
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('session_prompt')), findsOneWidget);
  });

  testWidgets('the welcome screen survives large text', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
        child: wrap(const WelcomeScreen(), api: FakeMeditationApi()),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
