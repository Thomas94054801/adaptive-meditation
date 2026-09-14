import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:adaptive_meditation/features/settings/settings_screen.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_notification_provider.dart';
import 'support/fakes.dart';
import 'support/harness.dart';
import 'support/preference_store.dart';

/// REM-01/02/05/06 as a person meets them on the settings screen.
void main() {
  late FakeNotificationProvider os;
  late PreferenceStubStore store;

  setUp(() {
    os = FakeNotificationProvider();
    store = PreferenceStubStore();
  });

  Widget screen() => wrap(
    const SettingsScreen(),
    api: FakeMeditationApi(),
    adapters: PlatformAdapters(notifications: os),
    durableStore: store,
  );

  final Finder toggle = find.byKey(const Key('settings_reminder'));
  final Finder state = find.byKey(const Key('settings_reminder_state'));

  Future<void> open(WidgetTester tester) async {
    await tester.pumpWidget(screen());
    await tester.pumpAndSettle();
  }

  testWidgets('REM-01: opening settings asks the OS for nothing', (
    WidgetTester tester,
  ) async {
    await open(tester);
    expect(os.permissionRequests, 0);
    expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
    expect(find.text('Off.'), findsOneWidget);
  });

  testWidgets('REM-02: turning it on explains first; Not now asks nothing', (
    WidgetTester tester,
  ) async {
    await open(tester);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('reminder_optin_title')), findsOneWidget);
    expect(os.permissionRequests, 0, reason: 'the sheet is not the prompt');
    await tester.tap(find.byKey(const Key('reminder_optin_not_now')));
    await tester.pumpAndSettle();
    expect(os.permissionRequests, 0);
    expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
  });

  testWidgets('REM-02/03: Continue asks exactly once and shows the schedule', (
    WidgetTester tester,
  ) async {
    await open(tester);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('reminder_optin_continue')));
    await tester.pumpAndSettle();
    expect(os.permissionRequests, 1);
    expect(tester.widget<SwitchListTile>(toggle).value, isTrue);
    expect(
      find.text('Scheduled daily at 08:00 (Asia/Taipei).'),
      findsOneWidget,
    );
    expect(os.held, isNotNull);
  });

  testWidgets('REM-06: denial leaves it off and says how to allow later', (
    WidgetTester tester,
  ) async {
    os.grantOnRequest = false;
    await open(tester);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('reminder_optin_continue')));
    await tester.pumpAndSettle();
    expect(os.permissionRequests, 1);
    expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
    expect(os.held, isNull);
    // Intent off and nothing scheduled reads as plain "Off."; the hint about
    // system settings appears when the intent is on but the OS says no.
    expect(find.text('Off.'), findsOneWidget);
  });

  testWidgets('REM-06b: intent on but permission revoked shows the hint', (
    WidgetTester tester,
  ) async {
    store.values[reminderEnabledKey] = 'true';
    store.values[reminderHourKey] = '7';
    store.values[reminderMinuteKey] = '30';
    os.permission = ReminderPermission.denied;
    await open(tester);
    expect(os.permissionRequests, 0, reason: 'never prompted on open');
    expect(tester.widget<SwitchListTile>(toggle).value, isTrue);
    expect(
      find.textContaining('notifications are off for this app'),
      findsOneWidget,
    );
    expect(state, findsOneWidget);
  });

  testWidgets('REM-05: turning it off cancels', (WidgetTester tester) async {
    await open(tester);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('reminder_optin_continue')));
    await tester.pumpAndSettle();
    expect(os.held, isNotNull);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(os.held, isNull);
    expect(store.values[reminderEnabledKey], 'false');
    expect(find.text('Off.'), findsOneWidget);
  });
}
