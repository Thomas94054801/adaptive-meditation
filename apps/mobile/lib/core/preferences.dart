import 'durable_store.dart';

/// The Program005 preferences, typed, over the durable store's key/value rows.
///
/// Two groups and nothing else: one presentation switch and one reminder
/// schedule. Defaults are here, not in the table, so a row that was never
/// written reads as the default and a row that was written reads as itself.
class Preferences {
  Preferences(this._store, {DateTime Function()? clock})
    : _clock = clock ?? DateTime.now;

  final DurableStore _store;
  final DateTime Function() _clock;

  /// Whether the opening may vary with the guest's history. Default on.
  Future<bool> adaptiveWordingEnabled() async {
    final String? raw = await _store.readPreference(adaptiveWordingKey);
    return raw == null ? true : raw == 'true';
  }

  /// Persist the switch. The future fails when the write fails; the caller
  /// must not report success on its own say-so.
  Future<void> setAdaptiveWordingEnabled(bool enabled) =>
      _store.writePreference(
        adaptiveWordingKey,
        enabled ? 'true' : 'false',
        nowMs: _clock().millisecondsSinceEpoch,
      );

  /// The reminder intent as stored: enabled, hour, minute, zone. Null fields
  /// mean never set.
  Future<ReminderPreference> reminder() async {
    final Map<String, String> all = await _store.readPreferences();
    return ReminderPreference(
      enabled: all[reminderEnabledKey] == 'true',
      hour: int.tryParse(all[reminderHourKey] ?? ''),
      minute: int.tryParse(all[reminderMinuteKey] ?? ''),
      zoneId: all[reminderZoneKey],
    );
  }

  Future<void> setReminder(ReminderPreference value) async {
    final int now = _clock().millisecondsSinceEpoch;
    await _store.writePreference(
      reminderEnabledKey,
      value.enabled ? 'true' : 'false',
      nowMs: now,
    );
    if (value.hour != null && value.minute != null) {
      await _store.writePreference(
        reminderHourKey,
        '${value.hour}',
        nowMs: now,
      );
      await _store.writePreference(
        reminderMinuteKey,
        '${value.minute}',
        nowMs: now,
      );
    }
    if (value.zoneId != null) {
      await _store.writePreference(reminderZoneKey, value.zoneId!, nowMs: now);
    }
  }

  /// The guest whose deletion is in progress, or null.
  Future<String?> deletionPending() =>
      _store.readPreference(deletionPendingKey);

  Future<void> markDeletionPending(String guestId) => _store.writePreference(
    deletionPendingKey,
    guestId,
    nowMs: _clock().millisecondsSinceEpoch,
  );

  Future<void> clearDeletionPending() =>
      _store.deletePreference(deletionPendingKey);
}

/// What the person asked for. Not whether the OS agreed (permission) and not
/// whether a request is actually scheduled; those are read separately.
class ReminderPreference {
  const ReminderPreference({
    required this.enabled,
    this.hour,
    this.minute,
    this.zoneId,
  });

  final bool enabled;
  final int? hour;
  final int? minute;
  final String? zoneId;

  bool get hasTime => hour != null && minute != null;

  ReminderPreference copyWith({
    bool? enabled,
    int? hour,
    int? minute,
    String? zoneId,
  }) => ReminderPreference(
    enabled: enabled ?? this.enabled,
    hour: hour ?? this.hour,
    minute: minute ?? this.minute,
    zoneId: zoneId ?? this.zoneId,
  );
}
