import 'dart:io';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_10y.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import '../core/reminders.dart';
import 'providers.dart';
import 'reminder_copy.dart';

/// The shipped [NotificationProvider] — flutter_local_notifications 22.3.1
/// with the device zone from flutter_timezone.
///
/// One daily OS recurrence at [reminderId]. Android is scheduled inexact and
/// allow-while-idle; no exact-alarm permission exists in this app. iOS is a
/// calendar trigger repeating on the time components in the named zone.
/// Whether a given OS delivers it under battery saving, disabled
/// notifications or force-stop is not promised anywhere.
///
/// Initialisation requests nothing: every iOS request flag is false, and the
/// only method that can show a prompt is [requestPermission].
class LocalNotificationProvider implements NotificationProvider {
  LocalNotificationProvider({
    FlutterLocalNotificationsPlugin? plugin,
    Future<String?> Function()? zoneReader,
    DateTime Function()? clock,
  }) : _plugin = plugin ?? FlutterLocalNotificationsPlugin(),
       _zoneReader = zoneReader ?? _deviceZone,
       _clock = clock ?? DateTime.now;

  static const int reminderId = 1;
  static const String channelId = 'practice_reminder';
  static const String channelName = 'Practice reminder';

  final FlutterLocalNotificationsPlugin _plugin;
  final Future<String?> Function() _zoneReader;
  final DateTime Function() _clock;
  bool _initialised = false;

  static Future<String?> _deviceZone() async {
    final TimezoneInfo info = await FlutterTimezone.getLocalTimezone();
    return info.identifier;
  }

  /// Zone database plus plugin initialisation. Idempotent; no prompt.
  Future<void> initialise() async {
    if (_initialised) {
      return;
    }
    tzdata.initializeTimeZones();
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('ic_reminder'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        ),
      ),
    );
    _initialised = true;
  }

  @override
  bool get isSupported => Platform.isAndroid || Platform.isIOS;

  @override
  Future<ReminderPermission> permissionState() async {
    await initialise();
    if (Platform.isAndroid) {
      // Below 13 there is no runtime permission; this reads whether the app's
      // notifications are actually enabled, which a person can switch off in
      // system settings on any version. Above 13 it reflects the grant.
      final bool? enabled = await _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()
          ?.areNotificationsEnabled();
      return switch (enabled) {
        true => ReminderPermission.granted,
        false => ReminderPermission.denied,
        null => ReminderPermission.undetermined,
      };
    }
    if (Platform.isIOS) {
      final NotificationsEnabledOptions? options = await _plugin
          .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin
          >()
          ?.checkPermissions();
      if (options == null) {
        return ReminderPermission.undetermined;
      }
      // iOS reports enabled or not; "never asked" and "denied" both read as
      // not granted here, and both mean the same thing for scheduling.
      return options.isEnabled
          ? ReminderPermission.granted
          : ReminderPermission.denied;
    }
    return ReminderPermission.unsupported;
  }

  @override
  Future<bool> requestPermission() async {
    await initialise();
    if (Platform.isAndroid) {
      final bool? granted = await _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()
          ?.requestNotificationsPermission();
      return granted ?? false;
    }
    if (Platform.isIOS) {
      final bool? granted = await _plugin
          .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin
          >()
          ?.requestPermissions(alert: true, sound: true);
      return granted ?? false;
    }
    return false;
  }

  @override
  Future<String?> localZoneId() async {
    await initialise();
    final String? identifier = await _zoneReader();
    if (identifier == null || identifier.isEmpty) {
      return null;
    }
    try {
      tz.getLocation(identifier);
    } on tz.LocationNotFoundException {
      return null;
    }
    return identifier;
  }

  @override
  Future<void> scheduleReminder(ReminderSchedule schedule) async {
    await initialise();
    final tz.Location zone = tz.getLocation(schedule.zoneId);
    final tz.TZDateTime first = nextOccurrence(zone, _clock(), schedule.time);
    await _plugin.zonedSchedule(
      id: reminderId,
      title: reminderTitle,
      body: reminderBody,
      scheduledDate: first,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          channelId,
          channelName,
          channelDescription: 'A daily reminder at the time you chose.',
          icon: 'ic_reminder',
          importance: Importance.defaultImportance,
          priority: Priority.defaultPriority,
        ),
        iOS: DarwinNotificationDetails(presentAlert: true, presentSound: true),
      ),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      matchDateTimeComponents: DateTimeComponents.time,
      payload: encodeReminderPayload(schedule),
    );
  }

  @override
  Future<ReminderSchedule?> scheduledReminder() async {
    await initialise();
    final List<PendingNotificationRequest> pending = await _plugin
        .pendingNotificationRequests();
    for (final PendingNotificationRequest request in pending) {
      if (request.id == reminderId) {
        return decodeReminderPayload(request.payload);
      }
    }
    return null;
  }

  @override
  Future<void> cancelReminder() async {
    await initialise();
    await _plugin.cancel(id: reminderId);
  }
}

/// The schedule rides in the request payload so the OS can hand it back: a
/// pending request carries no scheduled time of its own. A time and a zone
/// name are the reminder's settings, not anything about the person, and the
/// payload is never displayed.
String encodeReminderPayload(ReminderSchedule schedule) =>
    'v1|${schedule.time.hour}|${schedule.time.minute}|${schedule.zoneId}';

ReminderSchedule? decodeReminderPayload(String? payload) {
  if (payload == null) {
    return null;
  }
  final List<String> parts = payload.split('|');
  if (parts.length != 4 || parts[0] != 'v1') {
    return null;
  }
  final int? hour = int.tryParse(parts[1]);
  final int? minute = int.tryParse(parts[2]);
  if (hour == null || minute == null || parts[3].isEmpty) {
    return null;
  }
  return ReminderSchedule(
    time: ReminderTime(hour: hour, minute: minute),
    zoneId: parts[3],
  );
}
