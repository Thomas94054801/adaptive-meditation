import 'package:adaptive_meditation/platform/providers.dart';
import 'package:adaptive_meditation/platform/reminder_copy.dart';
import 'package:flutter_test/flutter_test.dart';

/// REM-08 - the reminder's words are fixed and carry nothing about anyone.
void main() {
  test('the copy is exactly the SDD\'s', () {
    expect(reminderTitle, 'Time for a mindful pause');
    expect(reminderBody, 'A few quiet minutes are waiting.');
  });

  test('no number, no state word, no identifier in either string', () {
    const List<String> forbidden = <String>[
      'stress',
      'anxiety',
      'anxious',
      'depress',
      'score',
      'streak',
      'guest',
      'session',
      'breath',
      'body',
      'kindness',
      'walking',
      'thought',
      'feeling',
      'awareness',
    ];
    for (final String text in <String>[reminderTitle, reminderBody]) {
      expect(RegExp(r'\d').hasMatch(text), isFalse, reason: text);
      for (final String word in forbidden) {
        expect(
          text.toLowerCase().contains(word),
          isFalse,
          reason: '$word in $text',
        );
      }
    }
  });

  test('the interface has no way to pass text', () {
    // Compile-time property, stated as a test so a future parameter shows up
    // as a failure here rather than as a silent capability.
    const ReminderSchedule schedule = ReminderSchedule(
      time: ReminderTime(hour: 8, minute: 0),
      zoneId: 'Asia/Taipei',
    );
    final Future<void> Function(ReminderSchedule) schedule1 =
        const DisabledNotificationProvider().scheduleReminder;
    expect(schedule1, isNotNull);
    expect(schedule.toString(), '08:00 Asia/Taipei');
  });
}
