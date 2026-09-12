import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/feedback/feedback_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite/sqflite.dart';

import 'support/fakes.dart';
import 'support/harness.dart';

/// FB-02, FB-07, FB-08 — the screen's ordering contract.
///
/// Program004R could lose a session's feedback to a dropped connection,
/// because the only copy lived in the outgoing request. These tests are about
/// the ordering that fixes it: commit locally, then tell the server once.
///
/// The store here is a stand-in that records calls and runs no SQL.
/// sqflite_common_ffi cannot be used inside a widget test - it performs real
/// asynchronous I/O that the widget binding's fake-async zone never completes,
/// and the FFI isolate then tears the test harness down mid-stream. Real SQL
/// behaviour is covered in durable_store_test.dart, which is a pure Dart test
/// with no binding; what is covered *here* is what the screen does in which
/// order, which is exactly what that test cannot see.
void main() {
  MeditationSession session() => const MeditationSession(
    id: 'session-1',
    checkInId: 'check-in-1',
    status: 'completed',
    recommendation: FakeMeditationApi.recommendation,
    plan: FakeMeditationApi.plan,
  );

  /// The feedback screen pushed onto a stack, as the app does.
  ///
  /// It must not be the first route: the screen leaves by popping back to the
  /// first one, so a harness that makes it the root would pop nothing and
  /// every "did it leave" assertion would be meaningless.
  Widget screen(MeditationApi api, {DurableStore? store}) => wrap(
    _PushHost(
      child: FeedbackScreen(
        session: session(),
        beforeState: sampleCheckIn,
        completed: true,
        completionRatio: 1,
      ),
    ),
    api: api,
    durableStore: store,
  );

  Future<void> open(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('open_feedback')));
    await tester.pumpAndSettle();
  }

  Future<void> submit(WidgetTester tester) async {
    // The button is below the fold on a test-sized viewport.
    await tester.scrollUntilVisible(
      find.byKey(const Key('feedback_submit')),
      120,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('feedback_submit')));
    await tester.pumpAndSettle();
  }

  testWidgets('FB-02: the local save happens before the request', (
    WidgetTester tester,
  ) async {
    final _RecordingStore store = _RecordingStore();
    final FakeMeditationApi api = FakeMeditationApi();
    await tester.pumpWidget(screen(api, store: store));
    await open(tester);
    await submit(tester);

    // Order is the contract: saved, then sent, then marked.
    expect(store.calls.first, 'save:session-1');
    expect(api.submittedFeedback, hasLength(1));
    expect(store.calls, contains('synced:session-1'));
    expect(store.calls.indexOf('save:session-1'), 0);
  });

  testWidgets('FB-07: a failed request leaves it pending and lets you leave', (
    WidgetTester tester,
  ) async {
    final _RecordingStore store = _RecordingStore();
    final FakeMeditationApi offline = FakeMeditationApi(
      failWith: const ApiException('no network'),
    );
    await tester.pumpWidget(screen(offline, store: store));
    await open(tester);
    await submit(tester);

    expect(store.calls, contains('save:session-1'));
    expect(
      store.calls,
      isNot(contains('synced:session-1')),
      reason: 'nothing was accepted, so nothing may be marked synced',
    );
    // The user is not trapped by an unreachable backend.
    expect(find.byType(FeedbackScreen), findsNothing);
  });

  testWidgets('FB-08: a failed local write reports failure and stays put', (
    WidgetTester tester,
  ) async {
    final _RecordingStore store = _RecordingStore(failSave: true);
    final FakeMeditationApi api = FakeMeditationApi();
    await tester.pumpWidget(screen(api, store: store));
    await open(tester);
    await submit(tester);

    expect(
      find.byType(FeedbackScreen),
      findsOneWidget,
      reason: 'nothing anywhere remembers what was typed, so it must not leave',
    );
    expect(find.textContaining('Could not save'), findsOneWidget);
    expect(
      api.submittedFeedback,
      isEmpty,
      reason: 'nothing is sent for something that was not saved',
    );
  });

  testWidgets('the pre-Program004R online path is unchanged without a store', (
    WidgetTester tester,
  ) async {
    // What stops this closeout regressing the existing behaviour: with no
    // durable store the screen posts straight to the backend, exactly as
    // before.
    final FakeMeditationApi api = FakeMeditationApi();
    await tester.pumpWidget(screen(api));
    await open(tester);
    await submit(tester);

    expect(api.submittedFeedback, hasLength(1));
    expect(find.byType(FeedbackScreen), findsNothing);
  });
}

/// Records what the screen asked for, and runs no SQL.
///
/// Extends the production class so the screen is exercised through its real
/// type rather than through an interface introduced for testing.
class _RecordingStore extends DurableStore {
  _RecordingStore({this.failSave = false}) : super(database: _UnusedDatabase());

  final bool failSave;
  final List<String> calls = <String>[];

  @override
  Future<void> saveFeedback({
    required String sessionId,
    required Map<String, dynamic> payload,
    required int nowMs,
  }) async {
    if (failSave) {
      throw const _DiskFull();
    }
    calls.add('save:$sessionId');
  }

  @override
  Future<void> markFeedbackSynced(
    String sessionId, {
    required int nowMs,
  }) async {
    calls.add('synced:$sessionId');
  }
}

class _DiskFull implements Exception {
  const _DiskFull();
  @override
  String toString() => 'no space left on device';
}

/// Satisfies the constructor and is never touched.
class _UnusedDatabase implements Database {
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnsupportedError('this stand-in store never reaches the database');
}

/// A first route that pushes the screen under test.
class _PushHost extends StatelessWidget {
  const _PushHost({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: ElevatedButton(
        key: const Key('open_feedback'),
        onPressed: () => Navigator.of(context).push<void>(
          MaterialPageRoute<void>(builder: (BuildContext _) => child),
        ),
        child: const Text('open'),
      ),
    ),
  );
}
