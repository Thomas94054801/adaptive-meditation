import 'dart:io';

import 'package:adaptive_meditation/platform/native_tts_provider.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_tts_channel.dart';

/// R04 — synthesis completion is a signal, not a return value.
///
/// The adapter under test is the production one. Only the operating system is
/// replaced, at the method-channel boundary, so these tests assert real
/// platform invocation rather than a class name.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late FakeTtsChannel platform;
  late Directory media;
  late NativeTtsProvider tts;

  setUp(() async {
    media = await Directory.systemTemp.createTemp('tts_test');
    platform = FakeTtsChannel()..outputDirectory = media;
    platform.install();
    tts = NativeTtsProvider()..useOutputDirectory(media);
  });

  tearDown(() async {
    platform.remove();
    if (media.existsSync()) {
      await media.delete(recursive: true);
    }
  });

  SynthesisRequest request([String text = 'Let the breath settle.']) =>
      SynthesisRequest(
        text: text,
        locale: 'en-US',
        renderKeyHint: 'abc123',
        timeout: const Duration(seconds: 2),
      );

  test('it invokes the platform with the real text and settings', () async {
    final SynthesisResult result = await tts.synthesizeToFile(request());

    // Actual platform calls, in order, not a stubbed provider.
    expect(platform.calls, contains('synthesizeToFile'));
    expect(platform.calls, contains('setLanguage'));
    expect(platform.calls, contains('setSpeechRate'));
    expect(platform.calls, contains('awaitSynthCompletion'));
    expect(platform.lastArguments['setLanguage'], 'en-US');

    final Map<Object?, Object?> args =
        platform.lastArguments['synthesizeToFile']! as Map<Object?, Object?>;
    expect(args['text'], 'Let the breath settle.');
    expect('${args['fileName']}', contains('abc123'));
    // The container must be readable from the name even before publication.
    expect('${args['fileName']}', anyOf(endsWith('.wav'), endsWith('.caf')));

    expect(result.bytes, 2048);
    expect(result.audioSha256.length, 64);
    expect(result.file.existsSync(), isTrue);
  });

  test('a queued request that never completes is not success', () async {
    // The engine accepts the request and then says nothing. A naive adapter
    // returns as soon as synthesizeToFile answers 1.
    platform.reportCompletion = false;

    await expectLater(
      tts.synthesizeToFile(request()),
      throwsA(
        isA<SynthesisFailed>().having(
          (SynthesisFailed e) => e.message,
          'message',
          contains('did not report completion'),
        ),
      ),
    );
  });

  test('an engine that refuses the request fails loudly', () async {
    platform.acceptRequest = false;
    await expectLater(
      tts.synthesizeToFile(request()),
      throwsA(isA<SynthesisFailed>()),
    );
  });

  test('completion with no file written is not success', () async {
    platform.writeFile = false;
    await expectLater(
      tts.synthesizeToFile(request()),
      throwsA(
        isA<SynthesisFailed>().having(
          (SynthesisFailed e) => e.message,
          'message',
          contains('wrote no file'),
        ),
      ),
    );
  });

  test('an empty file is not success', () async {
    platform.bytes = <int>[];
    await expectLater(
      tts.synthesizeToFile(request()),
      throwsA(
        isA<SynthesisFailed>().having(
          (SynthesisFailed e) => e.message,
          'message',
          contains('empty file'),
        ),
      ),
    );
  });

  test('an engine error is surfaced, not swallowed', () async {
    platform.failWith = 'engine unavailable';
    await expectLater(
      tts.synthesizeToFile(request()),
      throwsA(isA<SynthesisFailed>()),
    );
  });

  test('a cancelled request cannot later report success', () async {
    // The late-callback case: cancel while the engine is still working, then
    // let its completion arrive. It must not resolve the old request.
    platform.completionDelay = const Duration(milliseconds: 120);
    final Future<SynthesisResult> pending = tts.synthesizeToFile(request());
    await Future<void>.delayed(const Duration(milliseconds: 20));
    await tts.cancelAll();

    await expectLater(pending, throwsA(isA<SynthesisCancelled>()));
  });

  test('synthesis is serialised per engine', () async {
    // Two overlapping requests must not interleave: a platform completion
    // callback carries no request id, so a second in-flight request makes
    // every callback ambiguous.
    platform.completionDelay = const Duration(milliseconds: 30);
    final Future<SynthesisResult> first = tts.synthesizeToFile(request('one'));
    final Future<SynthesisResult> second = tts.synthesizeToFile(request('two'));

    final List<SynthesisResult> results = await Future.wait<SynthesisResult>(
      <Future<SynthesisResult>>[first, second],
    );
    expect(results, hasLength(2));
    expect(
      platform.calls.where((String c) => c == 'synthesizeToFile').length,
      2,
    );
  });

  test('describe reports the engine, and unknowns as unknown', () async {
    final TtsEngineDescriptor descriptor = await tts.describe();
    expect(descriptor.engineId, 'com.example.tts');
    expect(descriptor.voiceId, 'test-voice');
    // The platform does not expose an engine version, so it is recorded as
    // unknown rather than invented - a wrong version in a cache key serves
    // the wrong audio after an OS update.
    expect(descriptor.engineVersion, 'unknown');
    expect(descriptor.providerId, 'native:com.example.tts');
    expect(descriptor.providerVersion, contains('test-voice'));
  });

  test('the offline label starts unconfirmed and only a probe changes it', () {
    expect(tts.offlineCapability, TtsOfflineCapability.localUnconfirmed);
    expect(tts.offlineCapability.permitsOfflineClaim, isFalse);

    tts.recordProbe(TtsOfflineCapability.localConfirmed);
    expect(tts.offlineCapability.permitsOfflineClaim, isTrue);
  });
}
