import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/deletion.dart';
import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:adaptive_meditation/core/guest.dart';
import 'package:adaptive_meditation/core/preferences.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:adaptive_meditation/platform/secure_identity_store.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_notification_provider.dart';
import 'support/fakes.dart';
import 'support/preference_store.dart';

/// REM-07 - the deletion matrix. Every failure leaves a retryable state with
/// the same identity; only a fully confirmed run rotates it.
void main() {
  late FakeMeditationApi api;
  late PreferenceStubStore store;
  late FakeNotificationProvider os;
  late InMemoryIdentityStore identityStore;
  late GuestIdentity guest;

  DeletionProcedure procedure() => DeletionProcedure(
    api: api,
    store: store,
    notifications: os,
    guest: guest,
    clock: () => DateTime(2026),
  );

  setUp(() async {
    api = FakeMeditationApi();
    store = PreferenceStubStore(
      initial: <String, String>{
        adaptiveWordingKey: 'false',
        reminderEnabledKey: 'true',
        reminderHourKey: '8',
        reminderMinuteKey: '0',
      },
    );
    os = FakeNotificationProvider(permission: ReminderPermission.granted)
      ..held = const ReminderSchedule(
        time: ReminderTime(hour: 8, minute: 0),
        zoneId: 'Asia/Taipei',
      );
    identityStore = InMemoryIdentityStore();
    guest = GuestIdentity(identityStore);
    await guest.ensure();
  });

  test('all steps succeed: purge, cancel, then a fresh identity', () async {
    final String before = await guest.ensure();
    final DeletionOutcome outcome = await procedure().run();
    expect(outcome.complete, isTrue);
    expect(outcome.steps, <DeletionStep>[
      DeletionStep.markPending,
      DeletionStep.cancelReminder,
      DeletionStep.serverDelete,
      DeletionStep.localPurge,
      DeletionStep.rotate,
    ]);
    expect(api.deleteCalls, 1);
    expect(os.held, isNull);
    expect(store.calls, contains('forget:$before'));
    expect(store.values.containsKey(adaptiveWordingKey), isFalse);
    expect(store.values.containsKey(deletionPendingKey), isFalse);
    expect(await guest.ensure(), isNot(before));
  });

  test(
    'server failure: marker kept, identity kept, retry uses the same id',
    () async {
      api = FakeMeditationApi(
        failWith: const ApiException('503', statusCode: 503),
      );
      final String before = await guest.ensure();
      final DeletionOutcome outcome = await procedure().run();
      expect(outcome.complete, isFalse);
      expect(outcome.failedStep, DeletionStep.serverDelete);
      expect(store.values[deletionPendingKey], before);
      expect(store.calls.where((String c) => c.startsWith('forget:')), isEmpty);
      expect(await guest.ensure(), before, reason: 'not rotated');
      // The reminder intent was switched off before anything external ran.
      expect(store.values[reminderEnabledKey], 'false');

      // The server comes back; the retry addresses the same identity.
      api = FakeMeditationApi();
      final DeletionOutcome retry = await procedure().run();
      expect(retry.complete, isTrue);
      expect(store.calls, contains('forget:$before'));
      expect(await guest.ensure(), isNot(before));
    },
  );

  test('local purge failure: not success, marker kept, no rotation', () async {
    final _PurgeFailsStore failing = _PurgeFailsStore(store.values);
    final String before = await guest.ensure();
    final DeletionOutcome outcome = await DeletionProcedure(
      api: api,
      store: failing,
      notifications: os,
      guest: guest,
      clock: () => DateTime(2026),
    ).run();
    expect(outcome.complete, isFalse);
    expect(outcome.failedStep, DeletionStep.localPurge);
    expect(api.deleteCalls, 1, reason: 'the server delete did run');
    expect(failing.values[deletionPendingKey], before);
    expect(await guest.ensure(), before);
  });

  test(
    'reminder cancel failure: server delete and purge still run; not complete',
    () async {
      os.failCancel = true;
      final String before = await guest.ensure();
      final DeletionOutcome outcome = await procedure().run();
      expect(outcome.complete, isFalse);
      expect(outcome.failedStep, DeletionStep.cancelReminder);
      expect(api.deleteCalls, 1);
      expect(store.calls, contains('forget:$before'));
      expect(
        os.calls.where((String c) => c == 'cancel').length,
        2,
        reason: 'retried once',
      );
      expect(
        await guest.ensure(),
        before,
        reason: 'not rotated until cancel confirms',
      );
      expect(store.values[deletionPendingKey], before);

      os.failCancel = false;
      final DeletionOutcome retry =
          await procedure().resumeIfPending() as DeletionOutcome;
      expect(retry.complete, isTrue);
      expect(os.held, isNull);
      expect(await guest.ensure(), isNot(before));
    },
  );

  test('restart with a marker resumes; without one does nothing', () async {
    expect(await procedure().resumeIfPending(), isNull);
    api = FakeMeditationApi(failWith: const ApiException('offline'));
    await procedure().run();
    api = FakeMeditationApi();
    final DeletionOutcome? resumed = await procedure().resumeIfPending();
    expect(resumed, isNotNull);
    expect(resumed!.complete, isTrue);
    expect(
      await procedure().resumeIfPending(),
      isNull,
      reason: 'marker cleared',
    );
  });

  test(
    'a late reconcile during deletion cannot re-schedule the reminder',
    () async {
      api = FakeMeditationApi(failWith: const ApiException('offline'));
      await procedure().run(); // marker set, reminder cancelled, intent off
      expect(os.held, isNull);
      // ReminderController.reconcile is covered in reminder_controller_test;
      // here the fact it depends on: the marker is set and intent is off.
      final Preferences prefs = Preferences(store, clock: () => DateTime(2026));
      expect(await prefs.deletionPending(), isNotNull);
      expect((await prefs.reminder()).enabled, isFalse);
    },
  );
}

/// Preference writes succeed; the table purge throws.
class _PurgeFailsStore extends PreferenceStubStore {
  _PurgeFailsStore(Map<String, String> seed) : super(initial: seed);

  @override
  Future<void> forgetGuest(String guestId, {required int nowMs}) async {
    calls.add('forget:$guestId');
    throw const DiskFull();
  }
}
