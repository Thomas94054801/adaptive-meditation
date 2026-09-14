/// Store-sensitive capability boundaries.
///
/// Every capability Apple or Google reviews is declared here as an interface
/// with a deliberately inert V1 implementation. Nothing in this file requests a
/// runtime permission, and none of the deferred features has a call site, so a
/// permission string never reaches the manifests.
///
/// The declarations are mirrored in compliance/permissions.v1.yaml.
library;

import 'audio_session.dart';
import 'silent_audio_session.dart';
import 'tts_types.dart';

export 'tts_types.dart';

/// Account identity. Program001 is guest-only; no account exists to sign in to.
abstract interface class AuthProvider {
  bool get isSupported;

  /// Null in Program001. No placeholder identity is generated for a guest.
  Future<String?> currentAccountId();
}

class GuestOnlyAuthProvider implements AuthProvider {
  const GuestOnlyAuthProvider();

  @override
  bool get isSupported => false;

  @override
  Future<String?> currentAccountId() async => null;
}

/// Subscriptions and restore-purchase. Deferred to Program006.
abstract interface class BillingProvider {
  bool get isSupported;

  Future<bool> hasActiveEntitlement();

  Future<void> restorePurchases();
}

class UnavailableBillingProvider implements BillingProvider {
  const UnavailableBillingProvider();

  @override
  bool get isSupported => false;

  @override
  Future<bool> hasActiveEntitlement() async => false;

  @override
  Future<void> restorePurchases() async {}
}

/// What a probe established about a voice — never what was assumed.
///
/// Native does not mean offline. On Android the system engine may synthesise
/// over the network and the app cannot observe it directly, so a voice earns
/// [localConfirmed] only by rendering with the network down. Until then the
/// honest label is [localUnconfirmed]: still usable, just not something a store
/// listing or a privacy policy may describe as working offline.
enum TtsOfflineCapability {
  localConfirmed('local_confirmed'),
  localUnconfirmed('local_unconfirmed'),
  networkRequired('network_required'),
  unavailable('unavailable');

  const TtsOfflineCapability(this.wireValue);

  final String wireValue;

  /// Whether an offline claim may be made on this evidence.
  bool get permitsOfflineClaim => this == localConfirmed;
}

/// Spoken guidance. Device-native synthesis to a file is the shipped provider.
///
/// There is deliberately no `speak(text)`. Playback is always from a verified
/// local file, so a session's duration is known before it starts and the
/// elastic-silence arithmetic has something to work with. A live synthesiser on
/// the playback path would make both impossible.
abstract interface class TtsProvider {
  bool get isSupported;

  /// What has actually been established about this voice working offline.
  TtsOfflineCapability get offlineCapability;

  /// What this device will actually do, probed at runtime rather than assumed.
  Future<TtsEngineDescriptor> describe();

  /// Synthesise to a local file, returning the produced bytes' hash and the
  /// time synthesis took.
  Future<SynthesisResult> synthesizeToFile(SynthesisRequest request);

  Future<void> stop();
}

/// A provider for a device that cannot synthesise at all.
///
/// Not a default and not a convenience fallback: selecting this in production
/// means the app runs in an explicitly recorded degraded mode, and the release
/// wiring test refuses to let it be injected silently.
class UnavailableTtsProvider implements TtsProvider {
  const UnavailableTtsProvider();

  @override
  bool get isSupported => false;

  @override
  TtsOfflineCapability get offlineCapability =>
      TtsOfflineCapability.unavailable;

  @override
  Future<TtsEngineDescriptor> describe() async => const TtsEngineDescriptor(
    engineId: 'none',
    voiceId: 'none',
    locale: 'en-US',
    rate: defaultSpeechRate,
    pitch: defaultPitch,
    style: 'calm',
    engineVersion: 'none',
    encoding: 'none',
  );

  @override
  Future<SynthesisResult> synthesizeToFile(SynthesisRequest request) async {
    // async, so callers get a rejected future rather than a synchronous throw
    // out of something whose signature promises a future.
    throw const SynthesisFailed('no text-to-speech engine on this device');
  }

  @override
  Future<void> stop() async {}
}

/// Local storage for the guest identifier and local history.
abstract interface class SecureStorageProvider {
  Future<String?> read(String key);

  Future<void> write(String key, String value);

  Future<void> clear();
}

/// In-memory. Used by tests, and as the fallback when no persistent store is
/// available.
class InMemorySecureStorageProvider implements SecureStorageProvider {
  final Map<String, String> _values = <String, String>{};

  @override
  Future<String?> read(String key) async => _values[key];

  @override
  Future<void> write(String key, String value) async => _values[key] = value;

  @override
  Future<void> clear() async => _values.clear();
}

/// What the OS currently allows. `undetermined` is iOS before the first ask;
/// `unsupported` is a platform with no implementation behind the interface.
enum ReminderPermission { granted, denied, undetermined, unsupported }

/// A wall-clock time of day. What the person chose, nothing else.
class ReminderTime {
  const ReminderTime({required this.hour, required this.minute});

  final int hour;
  final int minute;

  @override
  bool operator ==(Object other) =>
      other is ReminderTime && other.hour == hour && other.minute == minute;

  @override
  int get hashCode => Object.hash(hour, minute);

  @override
  String toString() =>
      '${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}';
}

/// One daily reminder: a time of day in a named IANA zone. The zone is part
/// of the schedule because "08:00" means nothing without one.
class ReminderSchedule {
  const ReminderSchedule({required this.time, required this.zoneId});

  final ReminderTime time;
  final String zoneId;

  @override
  bool operator ==(Object other) =>
      other is ReminderSchedule && other.time == time && other.zoneId == zoneId;

  @override
  int get hashCode => Object.hash(time, zoneId);

  @override
  String toString() => '$time $zoneId';
}

/// Local reminders - Program005. One daily OS recurrence at one fixed id.
///
/// No text parameter anywhere: the copy is a constant inside the provider,
/// so nothing about the person can reach a lock screen by construction.
/// Nothing here requests a permission except [requestPermission], and the
/// only caller of that is the settings toggle's own opt-in flow.
abstract interface class NotificationProvider {
  bool get isSupported;

  /// What the OS allows right now. Below Android 13 there is no prompt and
  /// this reads whether the app's notifications are actually enabled.
  Future<ReminderPermission> permissionState();

  /// Show the OS prompt. True when granted.
  Future<bool> requestPermission();

  /// The device's IANA zone identifier, or null when it cannot be read or
  /// is unknown to the zone database. Null means "do not schedule", never
  /// "assume UTC".
  Future<String?> localZoneId();

  /// Replace the reminder (same id) with a daily recurrence at [schedule].
  /// Completes with an error when the OS refused; the caller shows that.
  Future<void> scheduleReminder(ReminderSchedule schedule);

  /// What the OS actually holds, or null when nothing is pending.
  Future<ReminderSchedule?> scheduledReminder();

  /// Cancel the reminder. A no-op when nothing is scheduled.
  Future<void> cancelReminder();
}

/// A platform with no reminder implementation, and the widget-test default.
///
/// Deliberately never calls a platform API. The production-wiring audit
/// refuses it on Android and iOS, so it cannot become the shipped provider by
/// omission.
class DisabledNotificationProvider implements NotificationProvider {
  const DisabledNotificationProvider();

  @override
  bool get isSupported => false;

  @override
  Future<ReminderPermission> permissionState() async =>
      ReminderPermission.unsupported;

  /// Always false, and deliberately never calls a platform permission API.
  @override
  Future<bool> requestPermission() async => false;

  @override
  Future<String?> localZoneId() async => null;

  @override
  Future<void> scheduleReminder(ReminderSchedule schedule) async {}

  @override
  Future<ReminderSchedule?> scheduledReminder() async => null;

  @override
  Future<void> cancelReminder() async {}
}

/// HealthKit / Health Connect / Garmin. Deferred to Program008.
abstract interface class HealthProvider {
  bool get isSupported;
}

class DeferredHealthProvider implements HealthProvider {
  const DeferredHealthProvider();

  @override
  bool get isSupported => false;
}

/// The set of adapters the app runs with.
class PlatformAdapters {
  PlatformAdapters({
    AuthProvider? auth,
    BillingProvider? billing,
    TtsProvider? tts,
    SecureStorageProvider? storage,
    NotificationProvider? notifications,
    HealthProvider? health,
    AudioSessionPort? audioSession,
  }) : auth = auth ?? const GuestOnlyAuthProvider(),
       billing = billing ?? const UnavailableBillingProvider(),
       tts = tts ?? const UnavailableTtsProvider(),
       storage = storage ?? InMemorySecureStorageProvider(),
       notifications = notifications ?? const DisabledNotificationProvider(),
       health = health ?? const DeferredHealthProvider(),
       audioSession = audioSession ?? SilentAudioSession();

  final AuthProvider auth;
  final BillingProvider billing;
  final TtsProvider tts;
  final SecureStorageProvider storage;
  final NotificationProvider notifications;
  final HealthProvider health;

  /// Audio focus, routes and background playback. The one capability
  /// Program004 actually creates, which is why the manifests change with it.
  final AudioSessionPort audioSession;
}
