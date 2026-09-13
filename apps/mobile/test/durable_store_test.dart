import 'dart:io';

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
  late String dbPath;

  setUp(() async {
    // A real file rather than :memory:, so the reopen test exercises what a
    // relaunch actually does. Deleted in tearDown.
    dbPath =
        '${Directory.systemTemp.path}/p4r_store_${DateTime.now().microsecondsSinceEpoch}.db';
    await databaseFactory.deleteDatabase(dbPath);
    db = await databaseFactory.openDatabase(
      dbPath,
      options: OpenDatabaseOptions(
        version: DurableStore.schemaVersion,
        onCreate: (Database db, int version) =>
            DurableStore.migrate(db, 0, version),
        onUpgrade: DurableStore.migrate,
      ),
    );
    store = DurableStore(database: db);
  });

  tearDown(() async {
    if (db.isOpen) {
      await db.close();
    }
    await databaseFactory.deleteDatabase(dbPath);
  });

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
        checkpoint(positionMs: 180000, confirmed: 'speech_2_sweep'),
      );

      // The same database, a new store object: what a relaunch looks like.
      final DurableStore reopened = DurableStore(database: db);
      final Checkpoint? found = await reopened.checkpointFor('s-1');

      expect(found, isNotNull);
      expect(found!.logicalPositionMs, 180000);
      expect(found.confirmedSegmentId, 'speech_2_sweep');
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

  group('feedback', () {
    Map<String, dynamic> payload({int after = 7}) => <String, dynamic>{
      'after_score': after,
      'helpfulness': 4,
      'completed': true,
      'notes': 'quieter',
    };

    test('FB-01: feedback survives a close and reopen', () async {
      await store.saveFeedback(
        sessionId: 's-1',
        payload: payload(),
        nowMs: 1000,
      );
      await db.close();

      // Reopened from the same file path, which is what a relaunch does.
      final Database reopened = await databaseFactory.openDatabase(
        dbPath,
        options: OpenDatabaseOptions(
          version: DurableStore.schemaVersion,
          onCreate: (Database d, int v) => DurableStore.migrate(d, 0, v),
          onUpgrade: DurableStore.migrate,
        ),
      );
      final DurableStore after = DurableStore(database: reopened);
      final StoredFeedback? found = await after.feedbackFor('s-1');

      expect(found, isNotNull);
      expect(found!.payload['after_score'], 7);
      expect(found.payload['notes'], 'quieter');
      expect(found.isPending, isTrue);
      db = reopened;
    });

    test(
      'FB-03: saving twice for one session leaves exactly one row',
      () async {
        await store.saveFeedback(
          sessionId: 's-1',
          payload: payload(),
          nowMs: 1000,
        );
        await store.saveFeedback(
          sessionId: 's-1',
          payload: payload(after: 9),
          nowMs: 2000,
        );

        final List<Map<String, Object?>> rows = await db.query('feedback');
        expect(rows, hasLength(1));
        expect((await store.feedbackFor('s-1'))!.payload['after_score'], 9);
      },
    );

    test('FB-04: editing preserves created_at and moves updated_at', () async {
      await store.saveFeedback(
        sessionId: 's-1',
        payload: payload(),
        nowMs: 1000,
      );
      await store.saveFeedback(
        sessionId: 's-1',
        payload: payload(after: 8),
        nowMs: 5000,
      );

      final StoredFeedback stored = (await store.feedbackFor('s-1'))!;
      expect(
        stored.createdAtMs,
        1000,
        reason: 'delete-then-insert would have lost this',
      );
      expect(stored.updatedAtMs, 5000);
    });

    test('FB-05: new and edited feedback is pending', () async {
      await store.saveFeedback(
        sessionId: 's-1',
        payload: payload(),
        nowMs: 1000,
      );
      expect(
        (await store.pendingFeedback()).map((StoredFeedback f) => f.sessionId),
        <String>['s-1'],
      );

      await store.markFeedbackSynced('s-1', nowMs: 2000);
      expect(await store.pendingFeedback(), isEmpty);

      // An edit the server has not seen goes back to pending.
      await store.saveFeedback(
        sessionId: 's-1',
        payload: payload(after: 3),
        nowMs: 3000,
      );
      expect((await store.feedbackFor('s-1'))!.isPending, isTrue);
    });

    test('FB-06: marking synced removes it from the pending set', () async {
      await store.saveFeedback(
        sessionId: 's-1',
        payload: payload(),
        nowMs: 1000,
      );
      await store.markFeedbackSynced('s-1', nowMs: 2000);

      final StoredFeedback stored = (await store.feedbackFor('s-1'))!;
      expect(stored.syncState, feedbackSynced);
      expect(stored.createdAtMs, 1000);
    });

    test('only pending and synced exist as states', () {
      // A state nothing produces is a state nothing handles correctly.
      expect(feedbackPending, 'pending');
      expect(feedbackSynced, 'synced');
    });

    test(
      'FB-09: guest deletion removes feedback with everything else',
      () async {
        await store.saveFeedback(
          sessionId: 's-1',
          payload: payload(),
          nowMs: 1000,
        );
        await store.saveCheckpoint(checkpoint());
        await store.enqueue(
          sessionId: 's-1',
          kind: OutboxKind.command,
          commandId: 'c',
          payload: <String, dynamic>{'n': 1},
        );

        await store.forgetGuest('guest-1', nowMs: 5000);

        expect(await store.feedbackFor('s-1'), isNull);
        expect(await store.pendingFeedback(), isEmpty);
        expect(await store.pending(), isEmpty);
        expect(await store.checkpointFor('s-1'), isNull);
      },
    );
  });

  group('schema', () {
    test('a v1 database upgrades to v2 without losing data', () async {
      // The upgrade path that matters: an installed v1 store holds the only
      // copy of a user's queued operations, so it must migrate in place.
      final String path = '${Directory.systemTemp.path}/p4r_v1_upgrade.db';
      await databaseFactory.deleteDatabase(path);

      final Database v1 = await databaseFactory.openDatabase(
        path,
        options: OpenDatabaseOptions(
          version: 1,
          onCreate: (Database d, int v) => DurableStore.migrate(d, 0, 1),
        ),
      );
      final DurableStore old = DurableStore(database: v1);
      await old.saveCheckpoint(
        const Checkpoint(
          sessionId: 'legacy',
          planHash: 'p',
          resolutionHash: 'r',
          audioMode: 'audible',
          runState: 'paused',
          commandSequence: 4,
          logicalPositionMs: 120000,
          updatedAtMs: 900,
        ),
      );
      await old.enqueue(
        sessionId: 'legacy',
        kind: OutboxKind.command,
        commandId: 'legacy-c',
        payload: <String, dynamic>{'command': 'pause'},
      );
      // v1 has no feedback table.
      expect(
        (await v1.query(
          'sqlite_master',
          where: 'type = ? AND name = ?',
          whereArgs: <Object?>['table', 'feedback'],
        )),
        isEmpty,
      );
      await v1.close();

      final Database v2 = await databaseFactory.openDatabase(
        path,
        options: OpenDatabaseOptions(
          version: DurableStore.schemaVersion,
          onCreate: (Database d, int v) => DurableStore.migrate(d, 0, v),
          onUpgrade: DurableStore.migrate,
        ),
      );
      final DurableStore upgraded = DurableStore(database: v2);

      // The pre-existing rows survived.
      final Checkpoint? kept = await upgraded.checkpointFor('legacy');
      expect(kept, isNotNull);
      expect(kept!.logicalPositionMs, 120000);
      expect(kept.commandSequence, 4);
      expect(await upgraded.pending(), hasLength(1));

      // And the new table works.
      await upgraded.saveFeedback(
        sessionId: 'legacy',
        payload: <String, dynamic>{'after_score': 6},
        nowMs: 1000,
      );
      expect((await upgraded.feedbackFor('legacy'))!.payload['after_score'], 6);
      expect(await v2.getVersion(), 2);

      await v2.close();
      await databaseFactory.deleteDatabase(path);
    });

    test('a fresh database opens directly at v2 with every table', () async {
      final List<Map<String, Object?>> tables = await db.query(
        'sqlite_master',
        columns: <String>['name'],
        where: 'type = ?',
        whereArgs: <Object?>['table'],
      );
      final Set<String> names = tables
          .map((Map<String, Object?> r) => r['name']! as String)
          .toSet();
      expect(
        names,
        containsAll(<String>[
          'checkpoints',
          'outbox',
          'deleted_guests',
          'feedback',
        ]),
      );
      expect(await db.getVersion(), 2);
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
