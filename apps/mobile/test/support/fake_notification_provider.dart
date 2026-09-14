import 'package:adaptive_meditation/platform/providers.dart';

/// Records every call. Permission, zone and failures are configurable, and
/// the "OS" holds at most one schedule, like the real one at a fixed id.
class FakeNotificationProvider implements NotificationProvider {
  FakeNotificationProvider({
    this.permission = ReminderPermission.denied,
    this.grantOnRequest = true,
    this.zone = 'Asia/Taipei',
  });

  ReminderPermission permission;
  bool grantOnRequest;
  String? zone;
  bool failSchedule = false;
  bool failCancel = false;

  ReminderSchedule? held;
  final List<String> calls = <String>[];

  int get permissionRequests =>
      calls.where((String c) => c == 'requestPermission').length;

  @override
  bool get isSupported => true;

  @override
  Future<ReminderPermission> permissionState() async {
    calls.add('permissionState');
    return permission;
  }

  @override
  Future<bool> requestPermission() async {
    calls.add('requestPermission');
    if (grantOnRequest) {
      permission = ReminderPermission.granted;
    } else {
      permission = ReminderPermission.denied;
    }
    return grantOnRequest;
  }

  @override
  Future<String?> localZoneId() async {
    calls.add('localZoneId');
    return zone;
  }

  @override
  Future<void> scheduleReminder(ReminderSchedule schedule) async {
    calls.add('schedule:$schedule');
    if (failSchedule) {
      throw StateError('the OS refused');
    }
    held = schedule;
  }

  @override
  Future<ReminderSchedule?> scheduledReminder() async {
    calls.add('scheduledReminder');
    return held;
  }

  @override
  Future<void> cancelReminder() async {
    calls.add('cancel');
    if (failCancel) {
      throw StateError('cancel refused');
    }
    held = null;
  }
}
