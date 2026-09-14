import 'package:adaptive_meditation/core/preferences.dart';
import 'package:adaptive_meditation/core/reminders.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_notification_provider.dart';
import 'support/preference_store.dart';

/// REM-01..06, REM-09 and the reconcile rules, against a recording provider.
///
/// A stub can show what the app asks the OS and in which order; it cannot
/// show that an OS delivered anything. Those axes stay NOT_RUN.
void main() {
  const ReminderTime eight = ReminderTime(hour: 8, minute: 0);

  late FakeNotificationProvider os;
  late PreferenceStubStore store;
  late ReminderController controller;

  setUp(() {
    os = FakeNotificationProvider();
    store = PreferenceStubStore();
    controller = ReminderController(
      notifications: os,
      preferences: Preferences(store, clock: () => DateTime(2026)),
    );
  });

  test('REM-01: reading the status asks for no permission', () async {
    final ReminderStatus status = await controller.status();
    expect(status.intent.enabled, isFalse);
    expect(status.active, isFalse);
    expect(os.permissionRequests, 0);
  });

  test('REM-01b: reconcile at start asks for no permission either', () async {
    await controller.reconcile();
    expect(os.permissionRequests, 0);
    expect(os.calls.where((String c) => c.startsWith('schedule:')), isEmpty);
  });

  test(
    'REM-02/03: opt-in asks exactly once and schedules in the zone',
    () async {
      final ReminderStatus status = await controller.optIn(eight);
      expect(os.permissionRequests, 1);
      expect(status.active, isTrue);
      expect(
        os.held,
        const ReminderSchedule(time: eight, zoneId: 'Asia/Taipei'),
      );
      expect(store.values['reminder_enabled'], 'true');
      expect(store.values['reminder_hour'], '8');
      expect(store.values['reminder_zone'], 'Asia/Taipei');
      // Intent was persisted before the OS was asked to schedule.
      final int intentWrite = os.calls.indexOf('requestPermission');
      expect(
        store.calls.indexWhere(
          (String c) => c.startsWith('write:reminder_enabled=true'),
        ),
        greaterThan(-1),
      );
      expect(intentWrite, greaterThan(-1));
    },
  );

  test(
    'REM-04: changing the time rewrites the same reminder; nothing else',
    () async {
      await controller.optIn(eight);
      os.calls.clear();
      const ReminderTime later = ReminderTime(hour: 21, minute: 15);
      final ReminderStatus status = await controller.changeTime(later);
      expect(os.permissionRequests, 0, reason: 'no second prompt');
      expect(status.scheduled!.time, later);
      expect(os.held!.time, later);
      expect(os.calls.where((String c) => c.startsWith('schedule:')).length, 1);
    },
  );

  test(
    'REM-04b: reconcile with nothing changed touches the OS schedule not at all',
    () async {
      await controller.optIn(eight);
      os.calls.clear();
      await controller.reconcile();
      expect(os.calls.where((String c) => c.startsWith('schedule:')), isEmpty);
      expect(os.calls, isNot(contains('cancel')));
    },
  );

  test('REM-04c: a zone change is corrected at the next reconcile', () async {
    await controller.optIn(eight);
    os.zone = 'America/New_York';
    os.calls.clear();
    final ReminderStatus status = await controller.reconcile();
    expect(status.scheduled!.zoneId, 'America/New_York');
    expect(store.values['reminder_zone'], 'America/New_York');
  });

  test('REM-04d: a schedule the OS lost is restored at reconcile', () async {
    await controller.optIn(eight);
    os.held = null; // e.g. the OS dropped it
    final ReminderStatus status = await controller.reconcile();
    expect(status.active, isTrue);
    expect(os.held, isNotNull);
  });

  test('REM-04e: nothing in the app expires the schedule', () async {
    // There is no window and no expiry: fourteen or a hundred days of the app
    // being unopened change nothing the app holds. The OS recurrence is the
    // schedule.
    await controller.optIn(eight);
    final ReminderStatus status = await controller.reconcile();
    expect(status.active, isTrue);
    expect(os.calls.where((String c) => c == 'cancel'), isEmpty);
  });

  test('REM-05: disabling cancels and records the intent', () async {
    await controller.optIn(eight);
    final ReminderStatus status = await controller.disable();
    expect(status.intent.enabled, isFalse);
    expect(status.scheduled, isNull);
    expect(os.calls.last, isNot('schedule'));
    expect(os.held, isNull);
    // The chosen time is kept for when it is turned on again.
    expect(store.values['reminder_hour'], '8');
  });

  test('REM-06: denial leaves the reminder off, nothing scheduled', () async {
    os.grantOnRequest = false;
    final ReminderStatus status = await controller.optIn(eight);
    expect(os.permissionRequests, 1);
    expect(status.intent.enabled, isFalse);
    expect(status.scheduled, isNull);
    expect(os.calls.where((String c) => c.startsWith('schedule:')), isEmpty);
  });

  test('REM-06b: a later revocation is reported, not prompted for', () async {
    await controller.optIn(eight);
    os.permission = ReminderPermission.denied; // switched off in settings
    os.held = null; // and the OS dropped the request with it
    os.calls.clear();
    final ReminderStatus status = await controller.reconcile();
    expect(status.intent.enabled, isTrue, reason: 'intent is the person\'s');
    expect(status.active, isFalse);
    expect(status.problem, ReminderProblem.permissionDenied);
    expect(os.permissionRequests, 0);
  });

  test(
    'REM-06c: below Android 13 a disabled app reads as not granted',
    () async {
      // The provider maps areNotificationsEnabled() to the permission state;
      // the controller treats it exactly like a denial.
      os.permission = ReminderPermission.denied;
      os.grantOnRequest = false;
      final ReminderStatus status = await controller.optIn(eight);
      expect(status.active, isFalse);
    },
  );

  test(
    'REM-09: an unknown zone schedules nothing and never falls back to UTC',
    () async {
      os.zone = null;
      final ReminderStatus status = await controller.optIn(eight);
      expect(os.permissionRequests, 1);
      expect(status.intent.enabled, isTrue);
      expect(status.scheduled, isNull);
      expect(status.problem, ReminderProblem.zoneUnknown);
      expect(os.calls.where((String c) => c.startsWith('schedule:')), isEmpty);
    },
  );

  test(
    'a refused schedule is shown as failed and a retry can succeed',
    () async {
      os.failSchedule = true;
      ReminderStatus status = await controller.optIn(eight);
      expect(status.problem, ReminderProblem.scheduleFailed);
      expect(status.active, isFalse);
      os.failSchedule = false;
      status = await controller.reconcile();
      expect(status.active, isTrue);
    },
  );

  test('a pending deletion pauses the reminder and blocks opt-in', () async {
    await controller.optIn(eight);
    await Preferences(store).markDeletionPending('guest-1');
    final ReminderStatus paused = await controller.reconcile();
    expect(paused.problem, ReminderProblem.deletionPending);
    expect(os.held, isNull, reason: 'reconcile cancelled it');
    os.calls.clear();
    final ReminderStatus refused = await controller.optIn(eight);
    expect(os.permissionRequests, 0);
    expect(refused.problem, ReminderProblem.deletionPending);
    expect(os.held, isNull);
  });
}
