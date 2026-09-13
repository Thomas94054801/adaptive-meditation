import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'providers.dart';

/// Why a secure-storage read or write did not succeed.
///
/// Distinguished rather than collapsed into a single failure, because the right
/// response differs: a locked device should be retried, a restored backup has
/// genuinely lost the value, and an unavailable keystore means this device
/// cannot hold an identity at all.
enum SecureStorageFailure {
  /// The device is locked and protected items are unreadable right now.
  deviceLocked,

  /// The item is gone - a restore onto a new device, or a keystore reset.
  itemUnavailable,

  /// The platform store could not be reached at all.
  storeUnavailable,
}

class SecureStorageException implements Exception {
  const SecureStorageException(this.failure, this.detail);

  final SecureStorageFailure failure;
  final String detail;

  /// True when retrying later could plausibly succeed.
  bool get isTransient => failure == SecureStorageFailure.deviceLocked;

  @override
  String toString() => 'SecureStorageException(${failure.name}): $detail';
}

/// Platform-secure storage for the guest identifier.
///
/// iOS: Keychain. Android: Keystore-backed EncryptedSharedPreferences.
///
/// Program002 kept the guest id in app-private preferences, which is readable
/// on a rooted or jailbroken device and is not what "secure storage" means to a
/// store reviewer. The identifier is still not a credential, but it is the only
/// handle a guest has on their own data, so it gets the platform's real store.
abstract interface class SecureIdentityStore {
  Future<String?> read(String key);

  Future<void> write(String key, String value);

  Future<void> delete(String key);

  Future<void> clear();
}

class PlatformSecureIdentityStore implements SecureIdentityStore {
  PlatformSecureIdentityStore({FlutterSecureStorage? storage})
    : _storage =
          storage ??
          const FlutterSecureStorage(
            // Android: Keystore-backed AES-GCM with RSA-OAEP key wrapping,
            // which is this package's default. migrateWithBackup stays false so
            // a restored backup does not carry an identity onto a new device.
            aOptions: AndroidOptions(migrateWithBackup: false),
            iOptions: IOSOptions(
              // Readable after first unlock, and never migrated to another
              // device: a restored install starts as a new guest rather than
              // inheriting an identity that another device still holds.
              accessibility: KeychainAccessibility.first_unlock_this_device,
            ),
          );

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } on PlatformException catch (error) {
      throw _translate(error);
    }
  }

  @override
  Future<void> write(String key, String value) async {
    try {
      await _storage.write(key: key, value: value);
    } on PlatformException catch (error) {
      throw _translate(error);
    }
  }

  @override
  Future<void> delete(String key) async {
    try {
      await _storage.delete(key: key);
    } on PlatformException catch (error) {
      throw _translate(error);
    }
  }

  @override
  Future<void> clear() async {
    try {
      await _storage.deleteAll();
    } on PlatformException catch (error) {
      throw _translate(error);
    }
  }

  static SecureStorageException _translate(PlatformException error) {
    final String code = error.code.toLowerCase();
    final String message = (error.message ?? '').toLowerCase();
    if (code.contains('locked') || message.contains('locked')) {
      return SecureStorageException(
        SecureStorageFailure.deviceLocked,
        error.message ?? error.code,
      );
    }
    if (code.contains('notfound') || message.contains('not found')) {
      return SecureStorageException(
        SecureStorageFailure.itemUnavailable,
        error.message ?? error.code,
      );
    }
    return SecureStorageException(
      SecureStorageFailure.storeUnavailable,
      error.message ?? error.code,
    );
  }
}

/// In-memory implementation for tests and for the documented fallback path.
class InMemoryIdentityStore implements SecureIdentityStore {
  InMemoryIdentityStore([Map<String, String>? seed])
    : _values = <String, String>{...?seed};

  final Map<String, String> _values;

  /// When set, every operation throws it. Used to exercise failure handling.
  SecureStorageException? failWith;

  @override
  Future<String?> read(String key) async {
    _maybeFail();
    return _values[key];
  }

  @override
  Future<void> write(String key, String value) async {
    _maybeFail();
    _values[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    _maybeFail();
    _values.remove(key);
  }

  @override
  Future<void> clear() async {
    _maybeFail();
    _values.clear();
  }

  void _maybeFail() {
    final SecureStorageException? failure = failWith;
    if (failure != null) {
      throw failure;
    }
  }
}

/// Bridges the Program002 [SecureStorageProvider] interface onto the secure
/// store, so existing call sites keep working while the backing store changes.
class SecureStorageProviderAdapter implements SecureStorageProvider {
  const SecureStorageProviderAdapter(this._store);

  final SecureIdentityStore _store;

  @override
  Future<String?> read(String key) => _store.read(key);

  @override
  Future<void> write(String key, String value) => _store.write(key, value);

  @override
  Future<void> clear() => _store.clear();
}
