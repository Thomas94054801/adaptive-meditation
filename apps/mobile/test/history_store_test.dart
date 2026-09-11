import 'package:adaptive_meditation/features/history/history_store.dart';
import 'package:flutter_test/flutter_test.dart';

SessionHistoryEntry entry(String id) => SessionHistoryEntry(
  sessionId: id,
  practiceName: 'Body Awareness',
  durationMinutes: 10,
  completed: true,
  recordedAt: DateTime(2026, 1, 1),
);

void main() {
  test('most recent session comes first', () {
    final SessionHistoryStore store = SessionHistoryStore()
      ..add(entry('a'))
      ..add(entry('b'));
    expect(
      store.entries.map((SessionHistoryEntry e) => e.sessionId).toList(),
      <String>['b', 'a'],
    );
  });

  test('the list is bounded and drops the oldest entry at the cap', () {
    final SessionHistoryStore store = SessionHistoryStore(maxEntries: 3);
    for (int i = 0; i < 10; i++) {
      store.add(entry('s$i'));
    }
    expect(store.entries.length, 3);
    expect(
      store.entries.map((SessionHistoryEntry e) => e.sessionId).toList(),
      <String>['s9', 's8', 's7'],
    );
  });

  test('the exposed list cannot be mutated by a caller', () {
    final SessionHistoryStore store = SessionHistoryStore()..add(entry('a'));
    expect(() => store.entries.add(entry('b')), throwsUnsupportedError);
  });
}
