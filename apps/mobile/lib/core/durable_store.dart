import 'dart:async';
import 'dart:convert';

import 'package:sqflite/sqflite.dart';

/// Fixed quotas — SDD A5.
///
/// Numbers rather than "N sessions, some row cap", so a test can assert them
/// and an operator can reason about disk use.
class OutboxQuota {
  const OutboxQuota({
    this.softRows = 10000,
    this.softBytes = 20 * 1024 * 1024,
    this.hardRows = 50000,
    this.hardBytes = 50 * 1024 * 1024,
    this.reserveRows = 1000,
    this.reserveBytes = 2 * 1024 * 1024,
    this.terminalCheckpointRows = 100,
    this.terminalCheckpointAge = const Duration(days: 30),
  });

  /// Above this, reconstructible telemetry is compacted.
  final int softRows;
  final int softBytes;

  /// Above this, no new run may be admitted as recoverable.
  final int hardRows;
  final int hardBytes;

  /// Always kept available for active-run operations, completion and feedback.
  final int reserveRows;
  final int reserveBytes;

  final int terminalCheckpointRows;
  final Duration terminalCheckpointAge;
}

/// What an outbox entry is for. Commands and observational events do not share
/// a deduplication namespace, and only one of them is droppable.
enum OutboxKind {
  /// Ordered, idempotent by command id, never dropped.
  command('command'),

  /// Unordered, idempotent by sequence, never dropped.
  evidence('evidence'),

  /// Reconstructible. The only thing compaction may remove.
  telemetry('telemetry');

  const OutboxKind(this.wireValue);
  final String wireValue;

  bool get isDroppable => this == telemetry;

  static OutboxKind fromWire(String value) => values.firstWhere(
    (OutboxKind k) => k.wireValue == value,
    orElse: () => OutboxKind.evidence,
  );
}

class OutboxEntry {
  const OutboxEntry({
    required this.id,
    required this.sessionId,
    required this.kind,
    required this.payload,
    this.commandId,
    this.sequence,
    this.attempts = 0,
    this.nextAttemptAtMs = 0,
  });

  final int id;
  final String sessionId;
  final OutboxKind kind;
  final Map<String, dynamic> payload;

  /// Stable across retries. Generating a new one turns one command into two.
  final String? commandId;

  final int? sequence;
  final int attempts;
  final int nextAttemptAtMs;
}

/// A session's resumable state, as it survives a process death.
class Checkpoint {
  const Checkpoint({
    required this.sessionId,
    required this.planHash,
    required this.resolutionHash,
    required this.audioMode,
    required this.runState,
    required this.commandSequence,
    required this.logicalPositionMs,
    this.confirmedSegmentId,
    this.pauseReason,
    this.terminal = false,
    this.updatedAtMs = 0,
  });

  final String sessionId;
  final String planHash;
  final String resolutionHash;
  final String audioMode;
  final String runState;
  final int commandSequence;

  /// Logical playback position, not a Stopwatch reading. A monotonic clock
  /// value means nothing across a reboot, so none is persisted.
  final int logicalPositionMs;

  final String? confirmedSegmentId;
  final String? pauseReason;
  final bool terminal;
  final int updatedAtMs;

  Map<String, Object?> toRow() => <String, Object?>{
    'session_id': sessionId,
    'plan_hash': planHash,
    'resolution_hash': resolutionHash,
    'audio_mode': audioMode,
    'run_state': runState,
    'command_sequence': commandSequence,
    'logical_position_ms': logicalPositionMs,
    'confirmed_segment_id': confirmedSegmentId,
    'pause_reason': pauseReason,
    'terminal': terminal ? 1 : 0,
    'updated_at_ms': updatedAtMs,
  };

  static Checkpoint fromRow(Map<String, Object?> row) => Checkpoint(
    sessionId: row['session_id']! as String,
    planHash: row['plan_hash']! as String,
    resolutionHash: row['resolution_hash']! as String,
    audioMode: row['audio_mode']! as String,
    runState: row['run_state']! as String,
    commandSequence: row['command_sequence']! as int,
    logicalPositionMs: row['logical_position_ms']! as int,
    confirmedSegmentId: row['confirmed_segment_id'] as String?,
    pauseReason: row['pause_reason'] as String?,
    terminal: (row['terminal']! as int) == 1,
    updatedAtMs: row['updated_at_ms']! as int,
  );
}

/// Thrown when the outbox is too full to promise recoverability.
class OutboxFull implements Exception {
  const OutboxFull(this.message);
  final String message;
  @override
  String toString() => 'OutboxFull: $message';
}

/// The durable local store — SDD A5 and A6.
///
/// Program004 kept unsent events in a Dart list on a `State` object, so
/// navigating away discarded them and an OS kill lost everything since the
/// last successful request. Recovery only appeared to work because the
/// *server* held the state, which needs the network — the opposite of the
/// offline contract.
///
/// This class is the single writer of local sequence and outbox state. The UI
/// does not open a second write path, because two writers cannot keep a
/// sequence monotonic.
class DurableStore {
  DurableStore({required Database database, this.quota = const OutboxQuota()})
    : _db = database;

  final Database _db;
  final OutboxQuota quota;

  static const int schemaVersion = 3;

  /// Create or upgrade the schema. Versioned independently of the server's.
  ///
  /// Additive by step, so an installed v1 database upgrades in place rather
  /// than being recreated: a user's queued operations and checkpoint are the
  /// only copy that exists, and dropping them to simplify a migration would
  /// throw away exactly what the durable store is for.
  static Future<void> migrate(Database db, int from, int to) async {
    // Each step is gated on the target too, not just the source. Without the
    // `to` bound, opening an older version still ran every later step, which
    // makes a v1 database indistinguishable from a v2 one and means the
    // upgrade path is never really exercised.
    if (from < 1 && to >= 1) {
      await db.execute('''
        CREATE TABLE IF NOT EXISTS checkpoints (
          session_id TEXT PRIMARY KEY,
          plan_hash TEXT NOT NULL,
          resolution_hash TEXT NOT NULL,
          audio_mode TEXT NOT NULL,
          run_state TEXT NOT NULL,
          command_sequence INTEGER NOT NULL,
          logical_position_ms INTEGER NOT NULL,
          confirmed_segment_id TEXT,
          pause_reason TEXT,
          terminal INTEGER NOT NULL DEFAULT 0,
          updated_at_ms INTEGER NOT NULL
        )
      ''');
      await db.execute('''
        CREATE TABLE IF NOT EXISTS outbox (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          command_id TEXT,
          sequence INTEGER,
          payload TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
          bytes INTEGER NOT NULL DEFAULT 0
        )
      ''');
      // Command identity is unique locally too, so a double enqueue cannot
      // become two commands on the wire.
      await db.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_command '
        'ON outbox(session_id, command_id) WHERE command_id IS NOT NULL',
      );
      await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_outbox_session ON outbox(session_id)',
      );
      // Guest deletion leaves a tombstone so a late request cannot resurrect
      // data the user asked to be removed.
      await db.execute('''
        CREATE TABLE IF NOT EXISTS deleted_guests (
          guest_id TEXT PRIMARY KEY,
          deleted_at_ms INTEGER NOT NULL
        )
      ''');
    }
    if (from < 2 && to >= 2) {
      // Program004R closeout. Feedback needs its own table rather than a
      // place in the outbox, because the outbox deletes rows on
      // acknowledgement and feedback has to stay readable after it syncs.
      //
      // session_id is the primary key and the whole identity. The server's
      // feedback endpoint already upserts by session id and takes no command
      // id, so a second idempotency namespace would exist only to be kept in
      // step with nothing.
      await db.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
          session_id TEXT PRIMARY KEY,
          payload TEXT NOT NULL,
          sync_state TEXT NOT NULL,
          created_at_ms INTEGER NOT NULL,
          updated_at_ms INTEGER NOT NULL
        )
      ''');
      await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_feedback_sync ON feedback(sync_state)',
      );
    }
    if (from < 3 && to >= 3) {
      // Program005. Preferences live here rather than in the secure store:
      // that store holds one value (the guest id) and on iOS is a keychain
      // item that outlives an uninstall, which a preference must not be. A
      // key/value table because there are four keys and a deletion marker,
      // not a profile.
      await db.execute('''
        CREATE TABLE IF NOT EXISTS preferences (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at_ms INTEGER NOT NULL
        )
      ''');
    }
  }

  // ----- preferences -------------------------------------------------------

  /// One preference, or null when it was never written.
  Future<String?> readPreference(String key) async {
    final List<Map<String, Object?>> rows = await _db.query(
      'preferences',
      columns: <String>['value'],
      where: 'key = ?',
      whereArgs: <Object?>[key],
      limit: 1,
    );
    if (rows.isEmpty) {
      return null;
    }
    return rows.single['value'] as String?;
  }

  /// Every preference, for a settings screen to render in one read.
  Future<Map<String, String>> readPreferences() async {
    final List<Map<String, Object?>> rows = await _db.query('preferences');
    return <String, String>{
      for (final Map<String, Object?> row in rows)
        row['key']! as String: row['value']! as String,
    };
  }

  /// Write one preference. Upsert by key; the caller learns of a failure by
  /// the future completing with an error, never by a silent no-op.
  Future<void> writePreference(
    String key,
    String value, {
    required int nowMs,
  }) async {
    await _db.rawInsert(
      'INSERT INTO preferences (key, value, updated_at_ms) VALUES (?, ?, ?) '
      'ON CONFLICT(key) DO UPDATE SET value = excluded.value, '
      'updated_at_ms = excluded.updated_at_ms',
      <Object?>[key, value, nowMs],
    );
  }

  Future<void> deletePreference(String key) async {
    await _db.delete(
      'preferences',
      where: 'key = ?',
      whereArgs: <Object?>[key],
    );
  }

  // ----- checkpoints -------------------------------------------------------

  /// Write a checkpoint. One transaction, and it never blocks stopping audio:
  /// callers stop the player first and persist afterwards.
  Future<void> saveCheckpoint(Checkpoint checkpoint) async {
    await _db.transaction<void>((Transaction txn) async {
      final List<Map<String, Object?>> existing = await txn.query(
        'checkpoints',
        columns: <String>['command_sequence', 'logical_position_ms'],
        where: 'session_id = ?',
        whereArgs: <Object?>[checkpoint.sessionId],
      );
      if (existing.isNotEmpty) {
        final int storedSequence = existing.first['command_sequence']! as int;
        if (checkpoint.commandSequence < storedSequence) {
          // Monotonic by construction: an older checkpoint is not news.
          return;
        }
      }
      await txn.insert(
        'checkpoints',
        checkpoint.toRow(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    });
  }

  Future<Checkpoint?> checkpointFor(String sessionId) async {
    final List<Map<String, Object?>> rows = await _db.query(
      'checkpoints',
      where: 'session_id = ?',
      whereArgs: <Object?>[sessionId],
    );
    return rows.isEmpty ? null : Checkpoint.fromRow(rows.first);
  }

  /// The run to offer on relaunch: the one that has not finished.
  Future<Checkpoint?> resumableCheckpoint() async {
    final List<Map<String, Object?>> rows = await _db.query(
      'checkpoints',
      where: 'terminal = 0',
      orderBy: 'updated_at_ms DESC',
      limit: 1,
    );
    return rows.isEmpty ? null : Checkpoint.fromRow(rows.first);
  }

  /// Prune synced terminal checkpoints past the retention quota.
  Future<int> pruneTerminalCheckpoints({required int nowMs}) async {
    final int cutoff = nowMs - quota.terminalCheckpointAge.inMilliseconds;
    final int byAge = await _db.delete(
      'checkpoints',
      where: 'terminal = 1 AND updated_at_ms < ?',
      whereArgs: <Object?>[cutoff],
    );

    final List<Map<String, Object?>> terminal = await _db.query(
      'checkpoints',
      columns: <String>['session_id'],
      where: 'terminal = 1',
      orderBy: 'updated_at_ms DESC',
    );
    int byCount = 0;
    if (terminal.length > quota.terminalCheckpointRows) {
      final Iterable<Object?> excess = terminal
          .skip(quota.terminalCheckpointRows)
          .map((Map<String, Object?> r) => r['session_id']);
      for (final Object? id in excess) {
        byCount += await _db.delete(
          'checkpoints',
          where: 'session_id = ?',
          whereArgs: <Object?>[id],
        );
      }
    }
    return byAge + byCount;
  }

  // ----- outbox ------------------------------------------------------------

  /// Queue an operation durably.
  ///
  /// A command already present under the same id is not enqueued twice.
  /// Telemetry is refused once the reserve is the only space left, so a full
  /// outbox cannot stop a completion or a feedback from being saved.
  Future<int> enqueue({
    required String sessionId,
    required OutboxKind kind,
    required Map<String, dynamic> payload,
    String? commandId,
    int? sequence,
    int nowMs = 0,
  }) async {
    final String encoded = jsonEncode(payload);
    final int bytes = encoded.length;

    return _db.transaction<int>((Transaction txn) async {
      final OutboxUsage usage = await _usageIn(txn);

      if (kind.isDroppable &&
          usage.rows + quota.reserveRows >= quota.softRows) {
        // Reconstructible and the reserve is approaching: drop it rather than
        // crowd out an operation that cannot be reconstructed.
        return -1;
      }
      if (usage.rows >= quota.hardRows || usage.bytes >= quota.hardBytes) {
        throw OutboxFull(
          'outbox is at its admission limit '
          '(${usage.rows} rows, ${usage.bytes} bytes)',
        );
      }

      if (commandId != null) {
        final List<Map<String, Object?>> existing = await txn.query(
          'outbox',
          columns: <String>['id'],
          where: 'session_id = ? AND command_id = ?',
          whereArgs: <Object?>[sessionId, commandId],
        );
        if (existing.isNotEmpty) {
          return existing.first['id']! as int;
        }
      }

      return txn.insert('outbox', <String, Object?>{
        'session_id': sessionId,
        'kind': kind.wireValue,
        'command_id': commandId,
        'sequence': sequence,
        'payload': encoded,
        'attempts': 0,
        'next_attempt_at_ms': nowMs,
        'bytes': bytes,
      });
    });
  }

  /// Whether a new recoverable run may be started.
  Future<bool> canAdmitNewRun() async {
    final OutboxUsage usage = await _usage();
    return usage.rows < quota.hardRows && usage.bytes < quota.hardBytes;
  }

  Future<List<OutboxEntry>> pending({int nowMs = 0, int limit = 100}) async {
    final List<Map<String, Object?>> rows = await _db.query(
      'outbox',
      where: 'next_attempt_at_ms <= ?',
      whereArgs: <Object?>[nowMs],
      orderBy: 'id ASC',
      limit: limit,
    );
    return rows
        .map(
          (Map<String, Object?> r) => OutboxEntry(
            id: r['id']! as int,
            sessionId: r['session_id']! as String,
            kind: OutboxKind.fromWire(r['kind']! as String),
            payload:
                jsonDecode(r['payload']! as String) as Map<String, dynamic>,
            commandId: r['command_id'] as String?,
            sequence: r['sequence'] as int?,
            attempts: r['attempts']! as int,
            nextAttemptAtMs: r['next_attempt_at_ms']! as int,
          ),
        )
        .toList(growable: false);
  }

  /// Remove entries the server confirmed. Only those.
  Future<int> acknowledge(Iterable<int> ids) async {
    if (ids.isEmpty) {
      return 0;
    }
    final String placeholders = List<String>.filled(ids.length, '?').join(',');
    return _db.delete(
      'outbox',
      where: 'id IN ($placeholders)',
      whereArgs: ids.toList(),
    );
  }

  /// Record a failed attempt and back off.
  Future<void> deferEntry(int id, {required int nextAttemptAtMs}) async {
    await _db.rawUpdate(
      'UPDATE outbox SET attempts = attempts + 1, next_attempt_at_ms = ? '
      'WHERE id = ?',
      <Object?>[nextAttemptAtMs, id],
    );
  }

  Future<OutboxUsage> usage() => _usage();

  Future<OutboxUsage> _usage() async => _usageIn(_db);

  Future<OutboxUsage> _usageIn(DatabaseExecutor executor) async {
    final List<Map<String, Object?>> rows = await executor.rawQuery(
      'SELECT count(*) AS rows_count, coalesce(sum(bytes), 0) AS total_bytes '
      'FROM outbox',
    );
    return OutboxUsage(
      rows: (rows.first['rows_count'] as int?) ?? 0,
      bytes: (rows.first['total_bytes'] as int?) ?? 0,
    );
  }

  // ----- feedback ----------------------------------------------------------

  /// Save feedback durably, in one transaction.
  ///
  /// An explicit UPSERT rather than delete-then-insert: replacement semantics
  /// would discard `created_at_ms` and, for a moment, leave no row at all for
  /// a session whose feedback the user has already written.
  ///
  /// A second save for the same session is an edit, not a new record. One
  /// session can never produce two rows, which the primary key enforces rather
  /// than the application remembering to.
  Future<void> saveFeedback({
    required String sessionId,
    required Map<String, dynamic> payload,
    required int nowMs,
  }) async {
    final String encoded = jsonEncode(payload);
    await _db.transaction<void>((Transaction txn) async {
      await txn.rawInsert(
        'INSERT INTO feedback '
        '(session_id, payload, sync_state, created_at_ms, updated_at_ms) '
        'VALUES (?, ?, ?, ?, ?) '
        'ON CONFLICT(session_id) DO UPDATE SET '
        '  payload = excluded.payload, '
        // An edit returns the row to pending: the server has not seen this
        // version yet, whatever it saw before.
        '  sync_state = ?, '
        '  updated_at_ms = excluded.updated_at_ms',
        <Object?>[
          sessionId,
          encoded,
          feedbackPending,
          nowMs,
          nowMs,
          feedbackPending,
        ],
      );
    });
  }

  Future<StoredFeedback?> feedbackFor(String sessionId) async {
    final List<Map<String, Object?>> rows = await _db.query(
      'feedback',
      where: 'session_id = ?',
      whereArgs: <Object?>[sessionId],
    );
    return rows.isEmpty ? null : StoredFeedback.fromRow(rows.first);
  }

  /// Feedback a later synchronisation may consume.
  ///
  /// This is the whole of "pending-sync" in Program004R: a queryable local
  /// state. There is no worker, no scheduler and no connectivity listener.
  Future<List<StoredFeedback>> pendingFeedback({int limit = 100}) async {
    final List<Map<String, Object?>> rows = await _db.query(
      'feedback',
      where: 'sync_state = ?',
      whereArgs: <Object?>[feedbackPending],
      orderBy: 'updated_at_ms ASC',
      limit: limit,
    );
    return rows.map(StoredFeedback.fromRow).toList(growable: false);
  }

  /// Record that the existing foreground request succeeded.
  ///
  /// Failing to mark it is safe: the row stays pending and the server upserts
  /// by session id, so a later attempt writes the same thing again. That is
  /// why there is no distributed-transaction machinery here.
  Future<void> markFeedbackSynced(
    String sessionId, {
    required int nowMs,
  }) async {
    await _db.update(
      'feedback',
      <String, Object?>{'sync_state': feedbackSynced, 'updated_at_ms': nowMs},
      where: 'session_id = ?',
      whereArgs: <Object?>[sessionId],
    );
  }

  // ----- deletion ----------------------------------------------------------

  /// Erase a guest locally and fence anything still in flight.
  ///
  /// The tombstone is what stops a late response from recreating data the user
  /// asked to be removed.
  Future<void> forgetGuest(String guestId, {required int nowMs}) async {
    await _db.transaction<void>((Transaction txn) async {
      await txn.delete('outbox');
      await txn.delete('checkpoints');
      await txn.delete('feedback');
      // Preferences go too, except the deletion marker: it is what lets a
      // relaunch finish the procedure this call is one step of, and the
      // procedure clears it itself once every step has confirmed.
      await txn.delete(
        'preferences',
        where: 'key <> ?',
        whereArgs: <Object?>[deletionPendingKey],
      );
      await txn.insert('deleted_guests', <String, Object?>{
        'guest_id': guestId,
        'deleted_at_ms': nowMs,
      }, conflictAlgorithm: ConflictAlgorithm.replace);
    });
  }

  Future<bool> isForgotten(String guestId) async {
    final List<Map<String, Object?>> rows = await _db.query(
      'deleted_guests',
      where: 'guest_id = ?',
      whereArgs: <Object?>[guestId],
    );
    return rows.isNotEmpty;
  }
}

/// Preference keys. Strings rather than an enum so a stored row that predates
/// a rename still reads.
const String adaptiveWordingKey = 'adaptive_wording_enabled';
const String reminderEnabledKey = 'reminder_enabled';
const String reminderHourKey = 'reminder_hour';
const String reminderMinuteKey = 'reminder_minute';
const String reminderZoneKey = 'reminder_zone';

/// Set to the guest id while a deletion is in progress (Program005 SDD 9.5).
/// Survives forgetGuest on purpose; cleared only when the procedure is done.
const String deletionPendingKey = 'deletion_pending';

/// The two sync states this program actually uses.
///
/// No `rejected` and no conflict states: nothing writes or reads them yet, and
/// a state no code produces is a state no code handles correctly.
const String feedbackPending = 'pending';
const String feedbackSynced = 'synced';

/// Feedback as it sits on disk.
class StoredFeedback {
  const StoredFeedback({
    required this.sessionId,
    required this.payload,
    required this.syncState,
    required this.createdAtMs,
    required this.updatedAtMs,
  });

  factory StoredFeedback.fromRow(Map<String, Object?> row) => StoredFeedback(
    sessionId: row['session_id']! as String,
    payload: jsonDecode(row['payload']! as String) as Map<String, dynamic>,
    syncState: row['sync_state']! as String,
    createdAtMs: row['created_at_ms']! as int,
    updatedAtMs: row['updated_at_ms']! as int,
  );

  final String sessionId;
  final Map<String, dynamic> payload;
  final String syncState;
  final int createdAtMs;
  final int updatedAtMs;

  bool get isPending => syncState == feedbackPending;
}

class OutboxUsage {
  const OutboxUsage({required this.rows, required this.bytes});
  final int rows;
  final int bytes;
}
