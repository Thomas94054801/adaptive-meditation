import 'package:adaptive_meditation/core/guest.dart';
import 'package:adaptive_meditation/platform/secure_identity_store.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('identity lifecycle', () {
    test('an id is generated once and then reused', () async {
      final GuestIdentity guest = GuestIdentity(InMemoryIdentityStore());
      final String first = await guest.ensure();
      for (int i = 0; i < 10; i++) {
        expect(await guest.ensure(), first);
      }
    });

    test('the id survives a new GuestIdentity over the same store', () async {
      final SecureIdentityStore store = InMemoryIdentityStore();
      final String first = await GuestIdentity(store).ensure();
      expect(await GuestIdentity(store).ensure(), first);
    });

    test('a restored id is reported as restored, a new one as created', () async {
      final SecureIdentityStore store = InMemoryIdentityStore();
      expect((await GuestIdentity(store).resolve()).source, GuestIdentitySource.created);
      expect((await GuestIdentity(store).resolve()).source, GuestIdentitySource.restored);
    });

    test('rotate issues a different id and persists it', () async {
      final SecureIdentityStore store = InMemoryIdentityStore();
      final GuestIdentity guest = GuestIdentity(store);
      final String first = await guest.ensure();
      final GuestIdentityResult rotated = await guest.rotate();
      expect(rotated.id, isNot(first));
      expect(rotated.isPersistent, isTrue);
      expect(await store.read(GuestIdentity.storageKey), rotated.id);
    });
  });

  group('secure storage failure handling', () {
    test('a locked device rethrows instead of minting a new identity', () async {
      // Retrying can succeed. Inventing an identity here would strand the
      // existing history under an id nobody holds.
      final InMemoryIdentityStore store = InMemoryIdentityStore()
        ..failWith = const SecureStorageException(
          SecureStorageFailure.deviceLocked,
          'device is locked',
        );
      await expectLater(
        GuestIdentity(store).resolve(),
        throwsA(isA<SecureStorageException>()),
      );
    });

    test('a permanent failure yields a reported ephemeral identity', () async {
      final InMemoryIdentityStore store = InMemoryIdentityStore()
        ..failWith = const SecureStorageException(
          SecureStorageFailure.storeUnavailable,
          'keystore unavailable',
        );
      final GuestIdentityResult result = await GuestIdentity(store).resolve();
      expect(result.source, GuestIdentitySource.ephemeral);
      expect(result.isPersistent, isFalse);
      expect(result.failure, isNotNull);
      expect(result.id, isNotEmpty);
    });

    test('a transient failure is distinguishable from a permanent one', () {
      const SecureStorageException locked = SecureStorageException(
        SecureStorageFailure.deviceLocked,
        '',
      );
      const SecureStorageException gone = SecureStorageException(
        SecureStorageFailure.itemUnavailable,
        '',
      );
      expect(locked.isTransient, isTrue);
      expect(gone.isTransient, isFalse);
    });

    test('a write failure still returns a usable ephemeral identity', () async {
      final _WriteFailingStore store = _WriteFailingStore();
      final GuestIdentityResult result = await GuestIdentity(store).resolve();
      expect(result.source, GuestIdentitySource.ephemeral);
      expect(result.failure?.failure, SecureStorageFailure.storeUnavailable);
    });
  });

  group('identifier properties', () {
    test('generated ids are RFC 4122 version 4', () {
      final RegExp uuidV4 = RegExp(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
      );
      for (int i = 0; i < 200; i++) {
        final String id = generateUuidV4();
        expect(uuidV4.hasMatch(id), isTrue, reason: id);
      }
    });

    test('ids are unique', () {
      final Set<String> seen = <String>{
        for (int i = 0; i < 2000; i++) generateUuidV4(),
      };
      expect(seen.length, 2000);
    });

    test('the id is not derived from the device', () async {
      // Two identities over separate stores must differ. If the id were derived
      // from anything device-scoped - a fingerprint, an advertising id - these
      // would collide, which is the failure this asserts against.
      final String a = await GuestIdentity(InMemoryIdentityStore()).ensure();
      final String b = await GuestIdentity(InMemoryIdentityStore()).ensure();
      expect(a, isNot(b));
    });

    test('the storage key is stable and readable', () async {
      final SecureIdentityStore store = InMemoryIdentityStore();
      final String id = await GuestIdentity(store).ensure();
      expect(await store.read(GuestIdentity.storageKey), id);
    });
  });
}

class _WriteFailingStore implements SecureIdentityStore {
  @override
  Future<String?> read(String key) async => null;

  @override
  Future<void> write(String key, String value) async =>
      throw const SecureStorageException(
        SecureStorageFailure.storeUnavailable,
        'read-only keystore',
      );

  @override
  Future<void> delete(String key) async {}

  @override
  Future<void> clear() async {}
}
