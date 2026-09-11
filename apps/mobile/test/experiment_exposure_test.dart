import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/core/reasons.dart';
import 'package:adaptive_meditation/features/recommendation/recommendation_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';
import 'support/harness.dart';

const CheckInReceipt receipt = CheckInReceipt(
  id: 'check-in-1',
  checkIn: sampleCheckIn,
);

void main() {
  group('exposure reporting', () {
    testWidgets('exposure is reported once the explanation is on screen', (
      WidgetTester tester,
    ) async {
      final FakeMeditationApi api = FakeMeditationApi();
      await tester.pumpWidget(
        wrap(
          const RecommendationScreen(
            receipt: receipt,
            recommendation: FakeMeditationApi.recommendation,
          ),
          api: api,
        ),
      );
      await tester.pumpAndSettle();

      expect(api.exposures, <String>[
        'recommendation_explanation_copy_v1:check-in-1',
      ]);
    });

    testWidgets('no variant means no exposure', (WidgetTester tester) async {
      final FakeMeditationApi api = FakeMeditationApi();
      await tester.pumpWidget(
        wrap(
          const RecommendationScreen(
            receipt: receipt,
            recommendation: Recommendation(
              practiceId: 'body_awareness',
              practicePublicName: 'Body Awareness',
              durationMinutes: 10,
              guidanceDensity: 0.7,
              reasonCodes: <String>['goal_overthinking'],
              engineVersion: '2',
              ruleSetVersion: '2',
              protocolVersion: '2',
            ),
          ),
          api: api,
        ),
      );
      await tester.pumpAndSettle();

      expect(api.exposures, isEmpty);
    });

    testWidgets('a failed exposure never interrupts the session', (
      WidgetTester tester,
    ) async {
      // An unrecorded exposure is a gap in analytics. Someone trying to
      // meditate must not see an error because of it.
      final FakeMeditationApi api = FakeMeditationApi(
        failWith: const ApiException('offline'),
      );
      await tester.pumpWidget(
        wrap(
          const RecommendationScreen(
            receipt: receipt,
            recommendation: FakeMeditationApi.recommendation,
          ),
          api: api,
        ),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('recommendation_start')), findsOneWidget);
      expect(find.byKey(const Key('recommendation_error')), findsNothing);
    });
  });

  group('variant wording', () {
    const List<String> codes = <String>[
      'goal_overthinking',
      'high_mental_activity',
      'high_stress',
    ];

    test('concise and contextual differ, and contextual contains concise', () {
      final String concise = explainRecommendationVariant(
        'Body Awareness',
        codes,
      )!;
      final String contextual = explainRecommendationVariant(
        'Body Awareness',
        codes,
        variant: 'contextual',
      )!;

      expect(contextual, isNot(concise));
      expect(contextual.contains(concise), isTrue);
      expect(contextual.length, greaterThan(concise.length));
    });

    test('an unknown variant falls back to concise', () {
      expect(
        explainRecommendationVariant('Body Awareness', codes, variant: 'nope'),
        explainRecommendationVariant('Body Awareness', codes),
      );
    });

    test('neither variant makes a clinical claim', () {
      for (final String variant in <String>['concise', 'contextual']) {
        final String text = explainRecommendationVariant(
          'Body Awareness',
          codes,
          variant: variant,
        )!.toLowerCase();
        for (final String banned in <String>[
          'treat',
          'cure',
          'diagnos',
          'therap',
          'disorder',
          'symptom',
        ]) {
          expect(text.contains(banned), isFalse, reason: '$variant: $banned');
        }
      }
    });

    testWidgets('the screen renders the assigned variant', (
      WidgetTester tester,
    ) async {
      // FakeMeditationApi assigns the contextual variant.
      await tester.pumpWidget(
        wrap(
          const RecommendationScreen(
            receipt: receipt,
            recommendation: FakeMeditationApi.recommendation,
          ),
          api: FakeMeditationApi(),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.textContaining('A busy mind settles faster'),
        findsOneWidget,
      );
    });
  });
}
