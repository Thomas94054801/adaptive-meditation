import 'package:adaptive_meditation/core/guest.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('an id is generated once and then reused', () async {
    final GuestIdentity guest = GuestIdentity(InMemorySecureStorageProvider());
    final String first = await guest.ensure();
    for (int i = 0; i < 10; i++) {
      expect(await guest.ensure(), first);
    }
  });

  test('the id survives a new GuestIdentity over the same storage', () async {
    final SecureStorageProvider storage = InMemorySecureStorageProvider();
    final String first = await GuestIdentity(storage).ensure();
    expect(await GuestIdentity(storage).ensure(), first);
  });

  test('reset forgets the id so the next session is a new guest', () async {
    final SecureStorageProvider storage = InMemorySecureStorageProvider();
    final GuestIdentity guest = GuestIdentity(storage);
    final String first = await guest.ensure();
    await guest.reset();
    final String second = await guest.ensure();
    expect(second, isNot(first));
  });

  test('generated ids are RFC 4122 version 4', () {
    final RegExp uuidV4 = RegExp(
      r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    );
    for (int i = 0; i < 200; i++) {
      expect(uuidV4.hasMatch(generateUuidV4()), isTrue, reason: generateUuidV4());
    }
  });

  test('ids are unique', () {
    final Set<String> seen = <String>{
      for (int i = 0; i < 2000; i++) generateUuidV4(),
    };
    expect(seen.length, 2000);
  });

  test('the id is not derived from the device', () async {
    // Two identities over separate storage must differ. If the id were derived
    // from anything device-scoped - a fingerprint, an advertising id - these
    // would collide, which is the failure this asserts against.
    final String a = await GuestIdentity(InMemorySecureStorageProvider()).ensure();
    final String b = await GuestIdentity(InMemorySecureStorageProvider()).ensure();
    expect(a, isNot(b));
  });

  test('the storage key is namespaced and readable', () async {
    final SecureStorageProvider storage = InMemorySecureStorageProvider();
    final String id = await GuestIdentity(storage).ensure();
    expect(await storage.read(GuestIdentity.storageKey), id);
  });
}
