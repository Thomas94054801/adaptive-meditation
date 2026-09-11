import 'package:adaptive_meditation/core/reasons.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('a single reason reads as one sentence', () {
    expect(
      explainRecommendation('Breath Awareness', <String>['goal_general']),
      'Breath Awareness, because you are practising generally.',
    );
  });

  test('several reasons are joined readably', () {
    expect(
      explainRecommendation('Body Awareness', <String>[
        'goal_overthinking',
        'high_mental_activity',
        'high_stress',
      ]),
      'Body Awareness, because your mind is busy, your thinking is running '
      'fast right now and stress is high right now.',
    );
  });

  test('an unknown code is dropped rather than shown raw', () {
    expect(
      explainRecommendation('Body Awareness', <String>[
        'goal_sleep',
        'a_code_the_client_does_not_know',
      ]),
      'Body Awareness, because you want to wind down for sleep.',
    );
  });

  test('no known codes gives no sentence at all', () {
    expect(explainRecommendation('Body Awareness', <String>['nonsense']), isNull);
    expect(explainRecommendation('Body Awareness', <String>[]), isNull);
  });

  test('no explanation makes a clinical claim', () {
    const List<String> everyCode = <String>[
      'goal_sleep',
      'goal_overthinking',
      'goal_stress',
      'goal_focus',
      'goal_emotional_reset',
      'goal_general',
      'high_mental_activity',
      'high_stress',
      'very_high_stress',
      'moderate_stress',
      'high_sleepiness',
      'grounding_preferred',
      'cognitive_observation',
      'stabilize_attention',
      'experienced_open_awareness',
      'recognize_reactivity',
      'experience_progression',
      'fallback_practice_used',
    ];
    final String text = explainRecommendation('Practice', everyCode)!;
    for (final String banned in <String>[
      'treat',
      'cure',
      'diagnos',
      'therap',
      'disorder',
      'symptom',
    ]) {
      expect(
        text.toLowerCase().contains(banned),
        isFalse,
        reason: 'explanation contained "$banned"',
      );
    }
  });
}
