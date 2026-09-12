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

  static const int schemaVersion = 1;

  /// Create the schema. Versioned independently of the server's.
  static Future<void> migrate(Database db, int from, int to) async {
    if (from < 1) {
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

  // ----- deletion ----------------------------------------------------------

  /// Erase a guest locally and fence anything still in flight.
  ///
  /// The tombstone is what stops a late response from recreating data the user
  /// asked to be removed.
  Future<void> forgetGuest(String guestId, {required int nowMs}) async {
    await _db.transaction<void>((Transaction txn) async {
      await txn.delete('outbox');
      await txn.delete('checkpoints');
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

class OutboxUsage {
  const OutboxUsage({required this.rows, required this.bytes});
  final int rows;
  final int bytes;
}
