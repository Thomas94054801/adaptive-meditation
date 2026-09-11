import 'dart:convert';

import 'package:adaptive_meditation/core/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const CheckIn checkIn = CheckIn(
    goal: Goal.overthinking,
    stress: 8,
    energy: 5,
    mentalActivity: 9,
    sleepiness: 2,
    availableMinutes: 10,
    experienceLevel: ExperienceLevel.beginner,
  );

  test('check-in serializes to the API wire format', () {
    expect(checkIn.toJson(), <String, dynamic>{
      'goal': 'overthinking',
      'stress': 8,
      'energy': 5,
      'mental_activity': 9,
      'sleepiness': 2,
      'available_minutes': 10,
      'experience_level': 'beginner',
    });
  });

  test('goal and experience wire values match the API enums', () {
    expect(Goal.values.map((Goal g) => g.wireValue).toList(), <String>[
      'stress',
      'overthinking',
      'focus',
      'sleep',
      'emotional_reset',
      'general',
    ]);
    expect(
      ExperienceLevel.values.map((ExperienceLevel e) => e.wireValue).toList(),
      <String>['beginner', 'intermediate', 'experienced'],
    );
  });

  test('available minutes match the API enum', () {
    expect(availableMinutesOptions, <int>[3, 5, 10, 15, 20]);
  });

  test('copyWith changes only the named field', () {
    final CheckIn updated = checkIn.copyWith(stress: 2);
    expect(updated.stress, 2);
    expect(updated.goal, checkIn.goal);
    expect(updated.mentalActivity, checkIn.mentalActivity);
  });

  test('a session response parses into the model', () {
    final Map<String, dynamic> json =
        jsonDecode('''
    {
      "id": "s1",
      "check_in_id": "c1",
      "status": "created",
      "created_at": "2026-01-01T00:00:00Z",
      "recommendation": {
        "practice_id": "body_awareness",
        "practice_public_name": "Body Awareness",
        "duration_minutes": 10,
        "guidance_density": 0.7,
        "reason_codes": ["goal_overthinking"],
        "recommendation_version": "1"
      },
      "plan": {
        "protocol_id": "body_awareness_v1",
        "protocol_version": 1,
        "practice_id": "body_awareness",
        "public_title": "Body Awareness",
        "total_seconds": 600,
        "guidance_density": 0.7,
        "stages": [
          {
            "id": "arrive",
            "intent": "establish_contact",
            "prompt": "Settle.",
            "start_offset_seconds": 0,
            "duration_seconds": 600,
            "guidance_cue_count": 10,
            "silence_after_seconds": 20
          }
        ]
      }
    }
    ''')
            as Map<String, dynamic>;

    final MeditationSession session = MeditationSession.fromJson(json);
    expect(session.id, 's1');
    expect(session.recommendation.practicePublicName, 'Body Awareness');
    expect(session.plan.stages.single.endOffsetSeconds, 600);
  });

  test('feedback omits optional fields when they are empty', () {
    const SessionFeedback minimal = SessionFeedback(
      afterScore: 3,
      helpfulness: 4,
      completed: true,
    );
    expect(minimal.toJson().containsKey('notes'), isFalse);
    expect(minimal.toJson().containsKey('before_score'), isFalse);

    const SessionFeedback full = SessionFeedback(
      afterScore: 3,
      helpfulness: 4,
      completed: true,
      beforeScore: 8,
      notes: 'steadier',
    );
    expect(full.toJson()['before_score'], 8);
    expect(full.toJson()['notes'], 'steadier');
  });
}
