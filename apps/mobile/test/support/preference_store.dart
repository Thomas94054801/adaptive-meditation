import 'package:adaptive_meditation/core/durable_store.dart';
import 'package:sqflite/sqflite.dart';

/// A stand-in durable store for widget tests: preferences in a map, every
/// call recorded, no SQL.
///
/// sqflite_common_ffi cannot run inside the widget binding (see
/// feedback_durability_test.dart); real SQL for the preferences table is in
/// durable_store_test.dart. What a screen does in which order is what this
/// stub makes visible.
class PreferenceStubStore extends DurableStore {
  PreferenceStubStore({Map<String, String>? initial, this.failWrites = false})
    : values = <String, String>{...?initial},
      super(database: _UnusedDatabase());

  final Map<String, String> values;
  final bool failWrites;
  final List<String> calls = <String>[];

  @override
  Future<String?> readPreference(String key) async {
    calls.add('read:$key');
    return values[key];
  }

  @override
  Future<Map<String, String>> readPreferences() async {
    calls.add('readAll');
    return Map<String, String>.of(values);
  }

  @override
  Future<void> writePreference(
    String key,
    String value, {
    required int nowMs,
  }) async {
    calls.add('write:$key=$value');
    if (failWrites) {
      throw const DiskFull();
    }
    values[key] = value;
  }

  @override
  Future<void> deletePreference(String key) async {
    calls.add('delete:$key');
    values.remove(key);
  }

  @override
  Future<void> forgetGuest(String guestId, {required int nowMs}) async {
    calls.add('forget:$guestId');
    if (failWrites) {
      throw const DiskFull();
    }
    values.removeWhere((String key, _) => key != deletionPendingKey);
  }

  @override
  Future<bool> isForgotten(String guestId) async =>
      calls.contains('forget:$guestId');
}

class DiskFull implements Exception {
  const DiskFull();
  @override
  String toString() => 'no space left on device';
}

class _UnusedDatabase implements Database {
  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnsupportedError('this stand-in store never reaches the database');
}
