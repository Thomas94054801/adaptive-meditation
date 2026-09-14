import 'package:timezone/timezone.dart' as tz;

import '../platform/providers.dart';
import 'preferences.dart';

/// The daily reminder's rules — Program005 SDD sections 9.1 and 9.5.
///
/// Three facts are kept apart and never conflated: what the person asked for
/// (the preference row), what the OS permits (read each time), and what the
/// OS actually holds (the pending request). "Reminder on" is shown only when
/// all three agree. No polling, no worker: [reconcile] runs at start and on
/// resume, and rewrites the schedule only when something changed.

/// Why the reminder is not active although the person asked for it.
enum ReminderProblem {
  /// The OS permission is not granted (denied, revoked, or, below Android
  /// 13, the app's notifications are switched off).
  permissionDenied,

  /// The device zone could not be read or is unknown to the zone database.
  /// Nothing is scheduled in UTC instead.
  zoneUnknown,

  /// The OS refused the schedule call; retrying is offered.
  scheduleFailed,

  /// A data deletion is in progress; reminders stay off until it completes.
  deletionPending,
}

class ReminderStatus {
  const ReminderStatus({
    required this.intent,
    required this.permission,
    required this.scheduled,
    this.problem,
  });

  final ReminderPreference intent;
  final ReminderPermission permission;
  final ReminderSchedule? scheduled;
  final ReminderProblem? problem;

  /// The person asked, the OS agreed, and a request is really pending.
  bool get active => intent.enabled && scheduled != null && problem == null;
}

/// The next calendar occurrence of [time] in [zone] after [nowUtc].
///
/// A calendar date in the zone, not "now plus 24 hours": across a DST
/// transition those differ by an hour, and the person asked for a clock time.
/// Spring-gap and autumn-overlap times are resolved by the `timezone`
/// package's rules and pinned by test, not assumed.
tz.TZDateTime nextOccurrence(
  tz.Location zone,
  DateTime nowUtc,
  ReminderTime time,
) {
  final tz.TZDateTime now = tz.TZDateTime.from(nowUtc.toUtc(), zone);
  tz.TZDateTime candidate = tz.TZDateTime(
    zone,
    now.year,
    now.month,
    now.day,
    time.hour,
    time.minute,
  );
  if (!candidate.isAfter(now)) {
    candidate = tz.TZDateTime(
      zone,
      now.year,
      now.month,
      now.day + 1,
      time.hour,
      time.minute,
    );
  }
  return candidate;
}

class ReminderController {
  ReminderController({
    required NotificationProvider notifications,
    required Preferences preferences,
  }) : _notifications = notifications,
       _preferences = preferences;

  final NotificationProvider _notifications;
  final Preferences _preferences;

  /// Read everything without changing anything. Never prompts.
  Future<ReminderStatus> status() async {
    final ReminderPreference intent = await _preferences.reminder();
    final ReminderPermission permission = await _notifications
        .permissionState();
    final ReminderSchedule? scheduled = await _notifications
        .scheduledReminder();
    return ReminderStatus(
      intent: intent,
      permission: permission,
      scheduled: scheduled,
      problem: await _problemFor(intent, permission, scheduled),
    );
  }

  /// The opt-in flow's last step: the person tapped Continue on the
  /// explanation sheet. The only place the OS prompt can appear.
  Future<ReminderStatus> optIn(ReminderTime time) async {
    if (await _preferences.deletionPending() != null) {
      return status();
    }
    final bool granted = await _notifications.requestPermission();
    if (!granted) {
      // Denial is a state, not an error: intent off, nothing scheduled.
      await _preferences.setReminder(
        ReminderPreference(
          enabled: false,
          hour: time.hour,
          minute: time.minute,
        ),
      );
      return status();
    }
    return _apply(time);
  }

  /// Change the time of a reminder that is already on. No prompt: if the
  /// permission has gone, the status says so.
  Future<ReminderStatus> changeTime(ReminderTime time) => _apply(time);

  Future<ReminderStatus> disable() async {
    final ReminderPreference intent = await _preferences.reminder();
    await _preferences.setReminder(intent.copyWith(enabled: false));
    await _notifications.cancelReminder();
    return status();
  }

  /// Start/resume: make the OS agree with the preference, touching the OS
  /// only when time, zone or enabled state changed or the request is gone.
  Future<ReminderStatus> reconcile() async {
    if (await _preferences.deletionPending() != null) {
      await _notifications.cancelReminder();
      return status();
    }
    final ReminderPreference intent = await _preferences.reminder();
    final ReminderSchedule? current = await _notifications.scheduledReminder();
    if (!intent.enabled || !intent.hasTime) {
      if (current != null) {
        await _notifications.cancelReminder();
      }
      return status();
    }
    if (await _notifications.permissionState() != ReminderPermission.granted) {
      return status();
    }
    final String? zone = await _notifications.localZoneId();
    if (zone == null) {
      return status();
    }
    final ReminderSchedule desired = ReminderSchedule(
      time: ReminderTime(hour: intent.hour!, minute: intent.minute!),
      zoneId: zone,
    );
    if (current != desired) {
      try {
        await _notifications.scheduleReminder(desired);
        await _preferences.setReminder(intent.copyWith(zoneId: zone));
      } catch (_) {
        // Reported through status(); nothing hides it.
      }
    }
    return status();
  }

  Future<ReminderStatus> _apply(ReminderTime time) async {
    // Intent first, so a crash after this line is a reminder the next
    // reconcile will finish scheduling, not one that was silently lost.
    ReminderPreference intent = (await _preferences.reminder()).copyWith(
      enabled: true,
      hour: time.hour,
      minute: time.minute,
    );
    await _preferences.setReminder(intent);
    if (await _notifications.permissionState() != ReminderPermission.granted) {
      return status();
    }
    final String? zone = await _notifications.localZoneId();
    if (zone == null) {
      return status();
    }
    try {
      await _notifications.scheduleReminder(
        ReminderSchedule(time: time, zoneId: zone),
      );
      intent = intent.copyWith(zoneId: zone);
      await _preferences.setReminder(intent);
    } catch (_) {
      // Left for status() to report as scheduleFailed.
    }
    return status();
  }

  Future<ReminderProblem?> _problemFor(
    ReminderPreference intent,
    ReminderPermission permission,
    ReminderSchedule? scheduled,
  ) async {
    if (await _preferences.deletionPending() != null) {
      return ReminderProblem.deletionPending;
    }
    if (!intent.enabled) {
      return null;
    }
    if (permission != ReminderPermission.granted) {
      return ReminderProblem.permissionDenied;
    }
    if (scheduled == null) {
      return await _notifications.localZoneId() == null
          ? ReminderProblem.zoneUnknown
          : ReminderProblem.scheduleFailed;
    }
    return null;
  }
}
