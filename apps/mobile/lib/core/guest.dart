import 'dart:math';

import '../platform/secure_identity_store.dart';

/// How the current guest identity was obtained.
enum GuestIdentitySource {
  /// Read back from platform-secure storage.
  restored,

  /// Freshly generated and persisted.
  created,

  /// Generated but *not* persisted, because secure storage was unavailable.
  ///
  /// The session works; the history will not be reachable after a restart. The
  /// UI must be able to say so rather than implying durability it does not have.
  ephemeral,
}

class GuestIdentityResult {
  const GuestIdentityResult(this.id, this.source, {this.failure});

  final String id;
  final GuestIdentitySource source;
  final SecureStorageException? failure;

  bool get isPersistent => source != GuestIdentitySource.ephemeral;
}

/// The guest's own identifier.
///
/// A random UUIDv4 held in platform-secure storage - Keychain on iOS,
/// Keystore-backed storage on Android. Deliberately *not* derived from the
/// device: no IMEI, IDFA, GAID, MAC address, hardware or vendor fingerprint.
///
/// It is not a credential. It is the only handle a guest has on their own data,
/// which is why it gets the platform's real store and why losing it silently
/// would be the worst outcome here.
class GuestIdentity {
  GuestIdentity(this._store);

  static const String storageKey = 'guest_id';

  final SecureIdentityStore _store;
  GuestIdentityResult? _cached;

  /// The current identity, restored or created.
  ///
  /// On a transient failure - a locked device - this rethrows rather than
  /// minting a new id, because a new id would strand the existing history under
  /// an identifier nobody holds. On a permanent failure it returns an ephemeral
  /// identity and reports it, so the caller can tell the user.
  Future<GuestIdentityResult> resolve() async {
    final GuestIdentityResult? cached = _cached;
    if (cached != null) {
      return cached;
    }

    String? stored;
    try {
      stored = await _store.read(storageKey);
    } on SecureStorageException catch (error) {
      if (error.isTransient) {
        // Retrying can succeed; inventing an identity cannot be undone.
        rethrow;
      }
      return _cached = GuestIdentityResult(
        generateUuidV4(),
        GuestIdentitySource.ephemeral,
        failure: error,
      );
    }

    if (stored != null && stored.isNotEmpty) {
      return _cached = GuestIdentityResult(
        stored,
        GuestIdentitySource.restored,
      );
    }

    final String created = generateUuidV4();
    try {
      await _store.write(storageKey, created);
    } on SecureStorageException catch (error) {
      return _cached = GuestIdentityResult(
        created,
        GuestIdentitySource.ephemeral,
        failure: error,
      );
    }
    return _cached = GuestIdentityResult(created, GuestIdentitySource.created);
  }

  /// The identifier alone, for call sites that only need the header value.
  Future<String> ensure() async => (await resolve()).id;

  /// Rotates to a new identity after the guest deletes their data.
  ///
  /// The old value is removed first. If that fails, no new identity is minted:
  /// leaving the old id in place is recoverable, whereas writing a new one over
  /// a failed delete would leave the old data addressable by a value still on
  /// the device.
  Future<GuestIdentityResult> rotate() async {
    await _store.delete(storageKey);
    _cached = null;
    return resolve();
  }

  /// Forgets the cached value without touching storage. Tests only.
  void forgetCache() => _cached = null;
}

final Random _random = Random.secure();

/// RFC 4122 version 4 UUID from a cryptographic source.
String generateUuidV4() {
  final List<int> bytes = List<int>.generate(16, (_) => _random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 1
  final String hex = bytes
      .map((int b) => b.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
