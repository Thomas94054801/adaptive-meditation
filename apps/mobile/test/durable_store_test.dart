import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// R10 and R11 — durability against real SQL.
///
/// These run the actual SQLite engine, not a mock. Program004 kept unsent
/// events in a Dart list on a State object: navigating away discarded them and
/// an OS kill lost everything since the last successful request, so recovery
/// only appeared to work because the server held the state — which needs the
/// network, the opposite of the offline contract.
void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  late Database db;
  late DurableStore store;

  setUp(() async {
    db = await databaseFactory.openDatabase(
      inMemoryDatabasePath,
      options: OpenDatabaseOptions(
        version: DurableStore.schemaVersion,
        onCreate: (Database db, int version) =>
            DurableStore.migrate(db, 0, version),
        onUpgrade: DurableStore.migrate,
      ),
    );
    store = DurableStore(database: db);
  });

  tearDown(() async => db.close());

  Checkpoint checkpoint({
    String sessionId = 's-1',
    int sequence = 1,
    int positionMs = 0,
    String runState = 'playing',
    bool terminal = false,
    String? confirmed,
    int updatedAtMs = 1000,
  }) => Checkpoint(
    sessionId: sessionId,
    planHash: 'p',
    resolutionHash: 'r',
    audioMode: 'audible',
    runState: runState,
    commandSequence: sequence,
    logicalPositionMs: positionMs,
    confirmedSegmentId: confirmed,
    terminal: terminal,
    updatedAtMs: updatedAtMs,
  );

  group('checkpoints', () {
    test('a checkpoint survives a store reopen', () async {
      await store.saveCheckpoint(
        checkpoint(positionMs: 180000, confirmed: 'speech_1_sweep'),
      );

      // The same database, a new store object: what a relaunch looks like.
      final DurableStore reopened = DurableStore(database: db);
      final Checkpoint? found = await reopened.checkpointFor('s-1');

      expect(found, isNotNull);
      expect(found!.logicalPositionMs, 180000);
      expect(found.confirmedSegmentId, 'speech_1_sweep');
      expect(found.commandSequence, 1);
    });

    test('an older checkpoint does not overwrite a newer one', () async {
      await store.saveCheckpoint(checkpoint(sequence: 9, positionMs: 90000));
      await store.saveCheckpoint(checkpoint(sequence: 2, positionMs: 1000));

      final Checkpoint? found = await store.checkpointFor('s-1');
      expect(found!.commandSequence, 9);
      expect(found.logicalPositionMs, 90000);
    });

    test('what is persisted is a logical position, not a stopwatch', () async {
      // A monotonic clock reading means nothing across a reboot, so none is
      // stored. The row's columns are the contract.
      await store.saveCheckpoint(checkpoint(positionMs: 42000));
      final List<Map<String, Object?>> rows = await db.query('checkpoints');
      expect(rows.first.keys, contains('logical_position_ms'));
      expect(
        rows.first.keys.where((String k) => k.contains('stopwatch')),
        isEmpty,
      );
    });

    test('the resumable run is the one that has not finished', () async {
      await store.saveCheckpoint(
        checkpoint(sessionId: 'done', terminal: true, updatedAtMs: 5000),
      );
      await store.saveCheckpoint(
        checkpoint(sessionId: 'live', updatedAtMs: 2000),
      );

      final Checkpoint? resumable = await store.resumableCheckpoint();
      expect(resumable!.sessionId, 'live');
    });

    test('terminal checkpoints are pruned by count and by age', () async {
      for (int i = 0; i < 105; i++) {
        await store.saveCheckpoint(
          checkpoint(sessionId: 's-$i', terminal: true, updatedAtMs: 1000 + i),
        );
      }
      final int pruned = await store.pruneTerminalCheckpoints(nowMs: 2000);
      expect(pruned, greaterThanOrEqualTo(5));

      final List<Map<String, Object?>> left = await db.query('checkpoints');
      expect(left.length, lessThanOrEqualTo(100));
    });
  });

  group('outbox', () {
    test('an entry survives and comes back in order', () async {
      await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.command,
        commandId: 'c-1',
        sequence: 1,
        payload: <String, dynamic>{'command': 'pause'},
      );
      await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.evidence,
        sequence: 2,
        payload: <String, dynamic>{'event_type': 'segment_started'},
      );

      final List<OutboxEntry> pending = await store.pending();
      expect(pending, hasLength(2));
      expect(pending.first.commandId, 'c-1');
      expect(pending.first.payload['command'], 'pause');
      expect(pending.last.kind, OutboxKind.evidence);
    });

    test('a command is never enqueued twice under the same id', () async {
      final int first = await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.command,
        commandId: 'c-1',
        payload: <String, dynamic>{'command': 'pause'},
      );
      final int second = await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.command,
        commandId: 'c-1',
        payload: <String, dynamic>{'command': 'pause'},
      );
      expect(second, first);
      expect(await store.pending(), hasLength(1));
    });

    test('acknowledging removes only the confirmed entries', () async {
      final int a = await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.command,
        commandId: 'a',
        payload: <String, dynamic>{'n': 1},
      );
      await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.command,
        commandId: 'b',
        payload: <String, dynamic>{'n': 2},
      );

      expect(await store.acknowledge(<int>[a]), 1);
      final List<OutboxEntry> left = await store.pending();
      expect(left, hasLength(1));
      expect(left.single.commandId, 'b');
    });

    test('a failed attempt backs off rather than spinning', () async {
      final int id = await store.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.command,
        commandId: 'c',
        payload: <String, dynamic>{'n': 1},
      );
      await store.deferEntry(id, nextAttemptAtMs: 10000);

      expect(await store.pending(nowMs: 0), isEmpty);
      final List<OutboxEntry> later = await store.pending(nowMs: 10000);
      expect(later.single.attempts, 1);
    });
  });

  group('R11: quotas', () {
    test('telemetry is dropped before the reserve is eaten', () async {
      final DurableStore tight = DurableStore(
        database: db,
        quota: const OutboxQuota(softRows: 12, reserveRows: 10),
      );
      // Ten commands: now rows + reserve >= soft, so telemetry is refused.
      for (int i = 0; i < 3; i++) {
        await tight.enqueue(
          sessionId: 's-1',
          kind: OutboxKind.command,
          commandId: 'c-$i',
          payload: <String, dynamic>{'n': i},
        );
      }
      final int dropped = await tight.enqueue(
        sessionId: 's-1',
        kind: OutboxKind.telemetry,
        payload: <String, dynamic>{'noise': true},
      );
      expect(dropped, -1, reason: 'reconstructible data yields to the reserve');
      expect(await tight.pending(), hasLength(3));
    });

    test('critical entries are still accepted inside the reserve', () async {
      final DurableStore tight = DurableStore(
        database: db,
        quota: const OutboxQuota(softRows: 4, reserveRows: 3, hardRows: 100),
      );
      for (int i = 0; i < 6; i++) {
        final int id = await tight.enqueue(
          sessionId: 's-1',
          kind: OutboxKind.evidence,
          sequence: i,
          payload: <String, dynamic>{'n': i},
        );
        expect(id, greaterThan(0), reason: 'evidence is never dropped');
      }
      expect(await tight.pending(limit: 10), hasLength(6));
    });

    test('the hard limit refuses admission rather than growing', () async {
      final DurableStore tight = DurableStore(
        database: db,
        quota: const OutboxQuota(softRows: 100, hardRows: 3, reserveRows: 1),
      );
      for (int i = 0; i < 3; i++) {
        await tight.enqueue(
          sessionId: 's-1',
          kind: OutboxKind.command,
          commandId: 'c-$i',
          payload: <String, dynamic>{'n': i},
        );
      }
      expect(await tight.canAdmitNewRun(), isFalse);
      await expectLater(
        tight.enqueue(
          sessionId: 's-2',
          kind: OutboxKind.command,
          commandId: 'x',
          payload: <String, dynamic>{'n': 9},
        ),
        throwsA(isA<OutboxFull>()),
      );
    });

    test('the declared quotas are the SDD numbers', () {
      const OutboxQuota quota = OutboxQuota();
      expect(quota.softRows, 10000);
      expect(quota.softBytes, 20 * 1024 * 1024);
      expect(quota.hardRows, 50000);
      expect(quota.hardBytes, 50 * 1024 * 1024);
      expect(quota.reserveRows, 1000);
      expect(quota.reserveBytes, 2 * 1024 * 1024);
      expect(quota.terminalCheckpointRows, 100);
      expect(quota.terminalCheckpointAge, const Duration(days: 30));
    });
  });

  group('R14: deletion', () {
    test(
      'forgetting a guest clears everything and leaves a tombstone',
      () async {
        await store.saveCheckpoint(checkpoint());
        await store.enqueue(
          sessionId: 's-1',
          kind: OutboxKind.command,
          commandId: 'c',
          payload: <String, dynamic>{'n': 1},
        );

        await store.forgetGuest('guest-1', nowMs: 5000);

        expect(await store.pending(), isEmpty);
        expect(await store.checkpointFor('s-1'), isNull);
        expect(await store.resumableCheckpoint(), isNull);
        expect(
          await store.isForgotten('guest-1'),
          isTrue,
          reason: 'the tombstone is what fences a late response',
        );
      },
    );

    test('a guest that was never deleted is not forgotten', () async {
      expect(await store.isForgotten('guest-2'), isFalse);
    });
  });

  test('commands and evidence do not share a dedupe namespace', () async {
    // An evidence row at sequence 1 must not stop a command at sequence 1:
    // they are different kinds of thing with different identity rules.
    await store.enqueue(
      sessionId: 's-1',
      kind: OutboxKind.evidence,
      sequence: 1,
      payload: <String, dynamic>{'event_type': 'segment_started'},
    );
    final int command = await store.enqueue(
      sessionId: 's-1',
      kind: OutboxKind.command,
      commandId: 'c-1',
      sequence: 1,
      payload: <String, dynamic>{'command': 'pause'},
    );
    expect(command, greaterThan(0));
    expect(await store.pending(), hasLength(2));
  });
}
