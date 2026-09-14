import 'package:adaptive_meditation/core/reminders.dart';
import 'package:adaptive_meditation/platform/local_notification_provider.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:timezone/data/latest_10y.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// The first instant a reminder is scheduled for - a calendar time in the
/// named zone, and what the `timezone` package does with DST edges.
///
/// The plugin recomputes later occurrences itself (Android: ZonedDateTime.of
/// in the zone; iOS: UNCalendarNotificationTrigger). Those are read in the
/// plugin's source and not measured here; see the SDD's NOT_RUN entries.
void main() {
  setUpAll(tzdata.initializeTimeZones);

  const ReminderTime nine = ReminderTime(hour: 9, minute: 0);

  test('later today when the time has not passed, in the zone', () {
    final tz.Location taipei = tz.getLocation('Asia/Taipei');
    // 2026-06-01 08:30 Taipei = 00:30 UTC
    final DateTime now = DateTime.utc(2026, 6, 1, 0, 30);
    final tz.TZDateTime next = nextOccurrence(taipei, now, nine);
    expect(next.location, taipei);
    expect(next.year, 2026);
    expect(next.month, 6);
    expect(next.day, 1);
    expect(next.hour, 9);
    expect(next.toUtc(), DateTime.utc(2026, 6, 1, 1, 0));
  });

  test('tomorrow when the time has passed today', () {
    final tz.Location taipei = tz.getLocation('Asia/Taipei');
    final DateTime now = DateTime.utc(2026, 6, 1, 3, 0); // 11:00 Taipei
    final tz.TZDateTime next = nextOccurrence(taipei, now, nine);
    expect(next.day, 2);
    expect(next.hour, 9);
  });

  test('exactly at the time is not "today": the next one is tomorrow', () {
    final tz.Location taipei = tz.getLocation('Asia/Taipei');
    final DateTime now = DateTime.utc(2026, 6, 1, 1, 0); // 09:00 Taipei
    expect(nextOccurrence(taipei, now, nine).day, 2);
  });

  test('across a DST start the next occurrence is 23 hours away, not 24', () {
    // New York springs forward 2026-03-08 at 02:00 EST -> 03:00 EDT.
    final tz.Location ny = tz.getLocation('America/New_York');
    final DateTime now = DateTime.utc(2026, 3, 7, 14, 30); // 09:30 EST Mar 7
    final tz.TZDateTime next = nextOccurrence(ny, now, nine);
    expect(next.day, 8);
    expect(next.hour, 9);
    // 09:00 EDT is 13:00 UTC; "now + 24h" would have been 14:30 UTC.
    expect(next.toUtc(), DateTime.utc(2026, 3, 8, 13, 0));
    expect(
      next.toUtc().difference(now),
      const Duration(hours: 22, minutes: 30),
    );
  });

  test(
    'a spring-gap time: the package\'s resolution is pinned, not assumed',
    () {
      // 02:30 does not exist on 2026-03-08 in New York. The timezone package
      // resolves TZDateTime(...) for a nonexistent local time by keeping the
      // pre-transition offset, which lands on 03:30 EDT (07:30 UTC). Android's
      // own recurrence (ZonedDateTime.of) shifts forward by the gap the same
      // way; iOS's UNCalendarNotificationTrigger is NOT_RUN.
      final tz.Location ny = tz.getLocation('America/New_York');
      final DateTime now = DateTime.utc(2026, 3, 8, 5, 0); // 00:00 EST Mar 8
      final tz.TZDateTime next = nextOccurrence(
        ny,
        now,
        const ReminderTime(hour: 2, minute: 30),
      );
      expect(next.toUtc(), DateTime.utc(2026, 3, 8, 7, 30));
      expect(next.hour, 3, reason: 'shifted forward by the gap');
    },
  );

  test(
    'an autumn-overlap time: the package picks one instant, pinned here',
    () {
      // 01:30 happens twice on 2026-11-01 in New York (EDT then EST). The
      // package resolves the ambiguous local time to the first (EDT, 05:30
      // UTC); Android's ZonedDateTime.of takes the earlier offset as well.
      final tz.Location ny = tz.getLocation('America/New_York');
      final DateTime now = DateTime.utc(2026, 11, 1, 4, 0); // 00:00 EDT Nov 1
      final tz.TZDateTime next = nextOccurrence(
        ny,
        now,
        const ReminderTime(hour: 1, minute: 30),
      );
      expect(next.toUtc(), DateTime.utc(2026, 11, 1, 5, 30));
    },
  );

  test('the payload round-trips a schedule and rejects anything else', () {
    const ReminderSchedule schedule = ReminderSchedule(
      time: ReminderTime(hour: 7, minute: 5),
      zoneId: 'Europe/London',
    );
    expect(decodeReminderPayload(encodeReminderPayload(schedule)), schedule);
    expect(decodeReminderPayload(null), isNull);
    expect(decodeReminderPayload('v0|7|5|Europe/London'), isNull);
    expect(decodeReminderPayload('v1|x|5|Europe/London'), isNull);
    expect(decodeReminderPayload('v1|7|5|'), isNull);
  });
}
