import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final PlatformAdapters adapters = PlatformAdapters();

  test('every deferred store capability reports itself unsupported', () {
    expect(adapters.auth.isSupported, isFalse);
    expect(adapters.billing.isSupported, isFalse);
    expect(adapters.tts.isSupported, isFalse);
    expect(adapters.notifications.isSupported, isFalse);
    expect(adapters.health.isSupported, isFalse);
  });

  test('no guest identity is invented', () async {
    expect(await adapters.auth.currentAccountId(), isNull);
  });

  test('notification permission is never granted and never prompts', () async {
    expect(await adapters.notifications.requestPermission(), isFalse);
  });

  test('billing reports no entitlement and restore is inert', () async {
    expect(await adapters.billing.hasActiveEntitlement(), isFalse);
    await expectLater(adapters.billing.restorePurchases(), completes);
  });

  test('the unavailable TTS provider refuses rather than pretending', () async {
    // There is no speak(): playback is always from a file. A device with no
    // engine must fail synthesis loudly, because a provider that silently
    // produces nothing is how Program004 shipped silent countdowns.
    await expectLater(
      adapters.tts.synthesizeToFile(
        const SynthesisRequest(
          text: 'anything',
          locale: 'en-US',
          renderKeyHint: 'k',
        ),
      ),
      throwsA(isA<SynthesisFailed>()),
    );
    await expectLater(adapters.tts.stop(), completes);
    expect(
      (await adapters.tts.describe()).engineId,
      'none',
      reason: 'it must not claim an engine it does not have',
    );
  });

  test('secure storage round-trips and clears', () async {
    await adapters.storage.write('guest_id', 'g-1');
    expect(await adapters.storage.read('guest_id'), 'g-1');
    await adapters.storage.clear();
    expect(await adapters.storage.read('guest_id'), isNull);
  });
}
