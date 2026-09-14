import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/recommendation/recommendation_screen.dart';
import 'package:adaptive_meditation/features/session/player_screen.dart';
import 'package:adaptive_meditation/features/session/transcript_sheet.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_audio_session.dart';
import 'support/fakes.dart';
import 'support/harness.dart';
import 'support/preference_store.dart';

/// Program005 Slice B - what travels with session creation and what the
/// person can read about it afterwards.
void main() {
  const Personalization returning = Personalization(
    policyVersion: '1',
    familiarityTier: 'returning',
    evidenceCount: 3,
    evidenceCapped: false,
    presentationVariant: 'returning',
    adaptiveWordingEnabled: true,
    personalized: true,
    providerId: 'null',
    aiAttempted: false,
    aiAccepted: false,
    reason: 'returning_to_this_practice',
    fallbackReason: 'provider_absent',
  );
  const Personalization fresh = Personalization(
    policyVersion: '1',
    familiarityTier: 'new',
    evidenceCount: 0,
    evidenceCapped: false,
    presentationVariant: 'canonical',
    adaptiveWordingEnabled: true,
    personalized: false,
    providerId: 'null',
    aiAttempted: false,
    aiAccepted: false,
    reason: 'first_time_with_this_practice',
    fallbackReason: 'provider_absent',
  );

  Widget recommendation(FakeMeditationApi api, {DurableStore? store}) => wrap(
    const RecommendationScreen(
      receipt: CheckInReceipt(id: 'c1', checkIn: sampleCheckIn),
      recommendation: FakeMeditationApi.recommendation,
    ),
    api: api,
    durableStore: store,
  );

  Future<void> start(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('recommendation_start')));
    await tester.pumpAndSettle();
  }

  group('transport', () {
    testWidgets('TX-01: the stored preference travels with the request', (
      WidgetTester tester,
    ) async {
      final FakeMeditationApi api = FakeMeditationApi();
      final PreferenceStubStore store = PreferenceStubStore(
        initial: <String, String>{adaptiveWordingKey: 'false'},
      );
      await tester.pumpWidget(recommendation(api, store: store));
      await start(tester);
      expect(api.createSessionAdaptiveWording, <bool?>[false]);
    });

    testWidgets('TX-02: the default preference travels as true', (
      WidgetTester tester,
    ) async {
      final FakeMeditationApi api = FakeMeditationApi();
      await tester.pumpWidget(
        recommendation(api, store: PreferenceStubStore()),
      );
      await start(tester);
      expect(api.createSessionAdaptiveWording, <bool?>[true]);
    });

    testWidgets('TX-03: with no store nothing is sent and the server decides', (
      WidgetTester tester,
    ) async {
      final FakeMeditationApi api = FakeMeditationApi();
      await tester.pumpWidget(recommendation(api));
      await start(tester);
      expect(api.createSessionAdaptiveWording, <bool?>[null]);
    });
  });

  group('explainability', () {
    late FakeAudioSession audio;
    setUp(() => audio = FakeAudioSession());
    tearDown(() async => audio.dispose());

    Widget player(Personalization? p) => wrap(
      PlayerScreen(
        session: MeditationSession(
          id: 'session-1',
          checkInId: 'check-in-1',
          status: 'created',
          recommendation: FakeMeditationApi.recommendation,
          plan: FakeMeditationApi.plan,
          planV2: FakeMeditationApi.typedPlan,
          personalization: p,
        ),
        plan: FakeMeditationApi.typedPlan,
        beforeState: sampleCheckIn,
        autoStart: false,
      ),
      api: FakeMeditationApi()..withTypedPlan = true,
      adapters: PlatformAdapters(audioSession: audio),
    );

    testWidgets(
      'EX-01: an adapted session says so in one line, with the reason',
      (WidgetTester tester) async {
        await tester.pumpWidget(player(returning));
        await tester.pump();
        expect(find.byKey(const Key('player_personalized')), findsOneWidget);
        expect(
          find.text('Wording adapted: returning to this practice'),
          findsOneWidget,
        );
      },
    );

    testWidgets('EX-02: a session that was not adapted shows no banner', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(player(fresh));
      await tester.pump();
      expect(find.byKey(const Key('player_personalized')), findsNothing);
      await tester.pumpWidget(player(null));
      await tester.pump();
      expect(find.byKey(const Key('player_personalized')), findsNothing);
    });

    test(
      'EX-03: the transcript line names variant, reason, policy and AI use',
      () {
        expect(
          TranscriptSheet.describe(returning),
          'Returning opening · returning to this practice · policy 1 · '
          'no AI wording',
        );
        expect(
          TranscriptSheet.describe(fresh),
          'Standard opening · first time with this practice · policy 1 · '
          'no AI wording',
        );
        // The null provider is never reported as AI use.
        expect(returning.usedAi, isFalse);
      },
    );

    test('EX-04: provenance parses from the wire and stays what it was', () {
      final Personalization parsed = Personalization.fromJson(<String, dynamic>{
        'schema_version': 1,
        'personalization_policy_version': '1',
        'familiarity_tier': 'returning',
        'evidence_count': 100,
        'evidence_capped': true,
        'presentation_variant': 'returning',
        'adaptive_wording_enabled': true,
        'personalized': true,
        'provider_id': 'null',
        'ai_attempted': false,
        'ai_accepted': false,
        'fallback_reason': 'provider_absent',
        'reason': 'returning_to_this_practice',
      });
      expect(parsed.evidenceCapped, isTrue);
      expect(parsed.reasonText, 'Returning to this practice');
      final MeditationSession old = MeditationSession.fromJson(
        <String, dynamic>{
          'id': 's',
          'check_in_id': 'c',
          'status': 'created',
          'recommendation': <String, dynamic>{
            'practice_id': 'body_awareness',
            'practice_public_name': 'Body Awareness',
            'duration_minutes': 10,
            'guidance_density': 0.65,
            'reason_codes': <String>[],
            'recommendation_version': '1',
          },
          'plan': <String, dynamic>{
            'protocol_id': 'body_awareness_v2',
            'practice_id': 'body_awareness',
            'public_title': 'Body Awareness',
            'total_seconds': 600,
            'guidance_density': 0.65,
            'stages': <dynamic>[],
          },
          'personalization': null,
        },
      );
      expect(old.personalization, isNull);
    });
  });
}
