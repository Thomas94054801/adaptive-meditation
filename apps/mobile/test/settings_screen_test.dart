import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:adaptive_meditation/features/settings/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';
import 'support/harness.dart';
import 'support/preference_store.dart';

/// Program005 Slice B - the one settings screen, wording switch only.
void main() {
  Widget screen(PreferenceStubStore store) => wrap(
    const SettingsScreen(),
    api: FakeMeditationApi(),
    durableStore: store,
  );

  final Finder toggle = find.byKey(const Key('settings_adaptive_wording'));

  bool switchValue(WidgetTester tester) =>
      tester.widget<SwitchListTile>(toggle).value;

  testWidgets('SET-01: the switch shows the stored value, off when off', (
    WidgetTester tester,
  ) async {
    final PreferenceStubStore store = PreferenceStubStore(
      initial: <String, String>{adaptiveWordingKey: 'false'},
    );
    await tester.pumpWidget(screen(store));
    await tester.pumpAndSettle();
    expect(switchValue(tester), isFalse);
    expect(store.calls, contains('read:$adaptiveWordingKey'));
  });

  testWidgets('SET-02: a never-written preference reads as on', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(screen(PreferenceStubStore()));
    await tester.pumpAndSettle();
    expect(switchValue(tester), isTrue);
  });

  testWidgets('SET-03: turning it off writes false to the store', (
    WidgetTester tester,
  ) async {
    final PreferenceStubStore store = PreferenceStubStore();
    await tester.pumpWidget(screen(store));
    await tester.pumpAndSettle();
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(switchValue(tester), isFalse);
    expect(store.values[adaptiveWordingKey], 'false');
    expect(store.calls, contains('write:$adaptiveWordingKey=false'));
    expect(find.byKey(const Key('settings_error')), findsNothing);
  });

  testWidgets('SET-04: a failed write is not reported as success', (
    WidgetTester tester,
  ) async {
    final PreferenceStubStore store = PreferenceStubStore(failWrites: true);
    await tester.pumpWidget(screen(store));
    await tester.pumpAndSettle();
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    // The switch shows what is stored - still on - and says why.
    expect(switchValue(tester), isTrue);
    expect(store.values.containsKey(adaptiveWordingKey), isFalse);
    expect(find.byKey(const Key('settings_error')), findsOneWidget);
    expect(find.textContaining('still on'), findsOneWidget);
  });
}
