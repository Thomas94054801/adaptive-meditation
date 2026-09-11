/// Store-sensitive capability boundaries.
///
/// Every capability Apple or Google reviews is declared here as an interface
/// with a deliberately inert V1 implementation. Nothing in this file requests a
/// runtime permission, and none of the deferred features has a call site, so a
/// permission string never reaches the manifests.
///
/// The declarations are mirrored in compliance/permissions.v1.yaml.
library;

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

/// Spoken guidance. Program001 renders stage text; audio arrives in Program004.
abstract interface class TtsProvider {
  bool get isSupported;

  Future<void> speak(String text);

  Future<void> stop();
}

class SilentTtsProvider implements TtsProvider {
  const SilentTtsProvider();

  @override
  bool get isSupported => false;

  @override
  Future<void> speak(String text) async {}

  @override
  Future<void> stop() async {}
}

/// Local storage for the guest identifier and local history.
abstract interface class SecureStorageProvider {
  Future<String?> read(String key);

  Future<void> write(String key, String value);

  Future<void> clear();
}

/// In-memory for Program001: nothing sensitive is held, and the app makes no
/// durability promise the implementation does not keep.
class InMemorySecureStorageProvider implements SecureStorageProvider {
  final Map<String, String> _values = <String, String>{};

  @override
  Future<String?> read(String key) async => _values[key];

  @override
  Future<void> write(String key, String value) async => _values[key] = value;

  @override
  Future<void> clear() async => _values.clear();
}

/// Reminders. Deferred to Program005; V1 shows no permission prompt.
abstract interface class NotificationProvider {
  bool get isSupported;

  Future<bool> requestPermission();
}

class DisabledNotificationProvider implements NotificationProvider {
  const DisabledNotificationProvider();

  @override
  bool get isSupported => false;

  /// Always false, and deliberately never calls a platform permission API.
  @override
  Future<bool> requestPermission() async => false;
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
  }) : auth = auth ?? const GuestOnlyAuthProvider(),
       billing = billing ?? const UnavailableBillingProvider(),
       tts = tts ?? const SilentTtsProvider(),
       storage = storage ?? InMemorySecureStorageProvider(),
       notifications = notifications ?? const DisabledNotificationProvider(),
       health = health ?? const DeferredHealthProvider();

  final AuthProvider auth;
  final BillingProvider billing;
  final TtsProvider tts;
  final SecureStorageProvider storage;
  final NotificationProvider notifications;
  final HealthProvider health;
}
