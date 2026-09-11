import 'dart:math';

import '../platform/providers.dart';

/// The guest's own identifier.
///
/// A random UUIDv4 and nothing else. Deliberately *not* derived from the
/// device: no hardware fingerprint, no IMEI, no advertising identifier, no
/// MAC address. It exists so a guest can find their own history and delete it,
/// which is the only reason server-side guest data is kept at all.
///
/// It is not a credential. Anyone holding the value can read that guest's
/// sessions, which is why nothing sensitive is stored against it and why the
/// app never transmits it anywhere but its own backend.
class GuestIdentity {
  GuestIdentity(this._storage);

  static const String storageKey = 'guest_id';

  final SecureStorageProvider _storage;
  String? _cached;

  /// The stored id, or a newly generated one saved on first use.
  Future<String> ensure() async {
    final String? cached = _cached;
    if (cached != null) {
      return cached;
    }
    final String? stored = await _storage.read(storageKey);
    if (stored != null && stored.isNotEmpty) {
      _cached = stored;
      return stored;
    }
    final String created = generateUuidV4();
    await _storage.write(storageKey, created);
    _cached = created;
    return created;
  }

  /// Forgets the local identifier. Used after the guest deletes their data, so
  /// the next session starts a genuinely new guest rather than re-populating
  /// the id they just erased.
  Future<void> reset() async {
    _cached = null;
    await _storage.clear();
  }
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
