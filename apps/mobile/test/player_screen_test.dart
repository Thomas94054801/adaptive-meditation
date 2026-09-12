import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/session/player_screen.dart';
import 'package:adaptive_meditation/features/session/transcript_sheet.dart';
import 'package:adaptive_meditation/platform/audio_session.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_audio_session.dart';
import 'support/fakes.dart';
import 'support/harness.dart';

/// Program004 Slice E - the player as a user meets it.
void main() {
  late FakeMeditationApi api;
  late FakeAudioSession audio;

  setUp(() {
    api = FakeMeditationApi()..withTypedPlan = true;
    audio = FakeAudioSession();
  });

  tearDown(() async => audio.dispose());

  MeditationSession session() => MeditationSession(
    id: 'session-1',
    checkInId: 'check-in-1',
    status: 'created',
    recommendation: FakeMeditationApi.recommendation,
    plan: FakeMeditationApi.plan,
    planV2: FakeMeditationApi.typedPlan,
  );

  Widget player({bool autoStart = false}) => wrap(
    PlayerScreen(
      session: session(),
      plan: FakeMeditationApi.typedPlan,
      beforeState: sampleCheckIn,
      autoStart: autoStart,
    ),
    api: api,
    adapters: PlatformAdapters(audioSession: audio),
  );

  testWidgets('shows the first line, the phase and the time left', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player());
    await tester.pump();

    expect(find.byKey(const Key('player_progress')), findsOneWidget);
    expect(find.byKey(const Key('player_remaining')), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('player_remaining'))).data,
      '10:04',
    );
  });

  testWidgets('preparing then starting walks the state machine', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player(autoStart: true));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(api.preparedSessions, <String>['session-1']);
    expect(
      api.playbackCommands.map((Map<String, dynamic> c) => c['command']),
      containsAllInOrder(<String>['prepare', 'resolved', 'start']),
    );
    // Each command carries its own id and a strictly increasing sequence.
    final List<int> sequences = api.playbackCommands
        .map((Map<String, dynamic> c) => c['sequence'] as int)
        .toList();
    expect(sequences, <int>[1, 2, 3]);
    expect(
      api.playbackCommands
          .map((Map<String, dynamic> c) => c['command_id'])
          .toSet()
          .length,
      3,
    );

    // Stop the ticker before the test ends.
    await tester.tap(find.byKey(const Key('player_pause_resume')));
    await tester.pump();
  });

  testWidgets('pause stops the clock and resume starts it again', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player(autoStart: true));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    await tester.tap(find.byKey(const Key('player_pause_resume')));
    await tester.pump();
    expect(
      tester
          .widget<Text>(
            find.descendant(
              of: find.byKey(const Key('player_pause_resume')),
              matching: find.byType(Text),
            ),
          )
          .data,
      'Resume',
    );
    expect(
      api.playbackCommands.map((Map<String, dynamic> c) => c['command']),
      contains('pause'),
    );

    final String remaining = tester
        .widget<Text>(find.byKey(const Key('player_remaining')))
        .data!;
    await tester.pump(const Duration(seconds: 5));
    expect(
      tester.widget<Text>(find.byKey(const Key('player_remaining'))).data,
      remaining,
      reason: 'a paused session must not lose time',
    );
  });

  testWidgets('losing headphones pauses and says why', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player(autoStart: true));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    audio.interrupt(AudioInterruption.wentPublic);
    await tester.pump();
    await tester.pump();

    expect(find.byKey(const Key('player_notice')), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('player_notice'))).data,
      contains('headphones disconnected'),
    );
    expect(
      api.playbackCommands.map((Map<String, dynamic> c) => c['command']),
      contains('interrupt'),
    );
  });

  testWidgets('focus returning does not resume on its own', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player(autoStart: true));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    audio.interrupt(AudioInterruption.focusLost);
    await tester.pump();
    await tester.pump();
    audio.regainFocus();
    await tester.pump();
    await tester.pump();

    // Still paused: the button offers Resume rather than Pause.
    expect(
      tester
          .widget<Text>(
            find.descendant(
              of: find.byKey(const Key('player_pause_resume')),
              matching: find.byType(Text),
            ),
          )
          .data,
      'Resume',
    );
    expect(
      api.playbackCommands.map((Map<String, dynamic> c) => c['command']),
      isNot(contains('resume')),
    );
  });

  testWidgets('another app holding audio blocks the start and says so', (
    WidgetTester tester,
  ) async {
    audio.grantFocus = false;
    await tester.pumpWidget(player(autoStart: true));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(
      tester.widget<Text>(find.byKey(const Key('player_notice'))).data,
      contains('Another app is using audio'),
    );
    expect(
      api.playbackCommands.map((Map<String, dynamic> c) => c['command']),
      isNot(contains('start')),
    );
  });

  testWidgets('the transcript shows every spoken line', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player());
    await tester.pump();

    await tester.tap(find.byKey(const Key('player_transcript')));
    await tester.pumpAndSettle();

    expect(find.byType(TranscriptSheet), findsOneWidget);
    for (int i = 0; i < FakeMeditationApi.typedPlan.speech.length; i++) {
      expect(find.byKey(Key('transcript_line_$i')), findsOneWidget);
    }
  });

  testWidgets('ending the session flushes the journal and releases audio', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(player(autoStart: true));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    await tester.tap(find.byKey(const Key('player_end')));
    await tester.pumpAndSettle();

    expect(
      api.playbackCommands.map((Map<String, dynamic> c) => c['command']),
      contains('abandon'),
    );
    expect(audio.deactivations, 1);
  });

  testWidgets('a backend that is down does not stop the meditation', (
    WidgetTester tester,
  ) async {
    final FakeMeditationApi offline = FakeMeditationApi(
      failWith: const ApiException('no network'),
    )..withTypedPlan = true;

    await tester.pumpWidget(
      wrap(
        PlayerScreen(
          session: session(),
          plan: FakeMeditationApi.typedPlan,
          beforeState: sampleCheckIn,
        ),
        api: offline,
        adapters: PlatformAdapters(audioSession: audio),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));

    // Playing regardless: the button offers Pause.
    expect(
      tester
          .widget<Text>(
            find.descendant(
              of: find.byKey(const Key('player_pause_resume')),
              matching: find.byType(Text),
            ),
          )
          .data,
      'Pause',
    );

    await tester.tap(find.byKey(const Key('player_pause_resume')));
    await tester.pump();
  });

  testWidgets('every control is labelled and reachable', (
    WidgetTester tester,
  ) async {
    final SemanticsHandle handle = tester.ensureSemantics();
    await tester.pumpWidget(player());
    await tester.pump();

    // Labels describe the action, not the word on the button: "Resume" alone
    // tells a screen-reader user nothing about what resumes.
    expect(find.bySemanticsLabel('Resume the session'), findsOneWidget);
    expect(
      find.bySemanticsLabel('End the session now and go to feedback'),
      findsOneWidget,
    );
    expect(find.bySemanticsLabel(RegExp('Session progress')), findsOneWidget);

    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    handle.dispose();
  });

  testWidgets('the player survives Dynamic Type at its maximum', (
    WidgetTester tester,
  ) async {
    // The spoken line is the entire point of the screen, so it must lay out
    // rather than overflow when someone has text at double size.
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
        child: player(),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('player_line')), findsOneWidget);
  });

  testWidgets('the transcript is reachable without starting the session', (
    WidgetTester tester,
  ) async {
    // The fallback rung for someone who is deaf or whose TTS is broken must
    // not require playing anything first.
    await tester.pumpWidget(player());
    await tester.pump();
    await tester.tap(find.byKey(const Key('player_transcript')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('transcript_title')), findsOneWidget);
  });
}
