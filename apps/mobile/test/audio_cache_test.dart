import 'dart:io';

import 'package:adaptive_meditation/core/audio_cache.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

/// R05 — immutable outputs, verification, and pins that survive.
void main() {
  late Directory root;
  late AudioCache cache;

  setUp(() async {
    root = await Directory.systemTemp.createTemp('cache_test');
    cache = AudioCache(root: root);
    await cache.ensureReady();
  });

  tearDown(() async {
    if (root.existsSync()) {
      await root.delete(recursive: true);
    }
  });

  Future<File> temporary(List<int> bytes, [String name = 'a.part.wav']) async {
    final File file = File('${root.path}/$name');
    await file.writeAsBytes(bytes);
    return file;
  }

  String hashOf(List<int> bytes) => sha256.convert(bytes).toString();

  test('publishing is atomic and content-addressed', () async {
    final List<int> bytes = <int>[1, 2, 3, 4, 5];
    final File published = await cache.publish(
      temporary: await temporary(bytes),
      audioSha256: hashOf(bytes),
      container: 'wav',
    );
    expect(published.path, endsWith('${hashOf(bytes)}.wav'));
    expect(published.existsSync(), isTrue);
    // No temporary left behind under a name a reader could mistake for final.
    expect(File('${root.path}/a.part.wav').existsSync(), isFalse);
  });

  test('publishing refuses bytes that do not match their hash', () async {
    final File file = await temporary(<int>[1, 2, 3]);
    await expectLater(
      cache.publish(temporary: file, audioSha256: 'f' * 64, container: 'wav'),
      throwsA(isA<AudioCacheError>()),
    );
    // And it does not leave the rejected work on disk.
    expect(file.existsSync(), isFalse);
  });

  test('publishing refuses an empty file', () async {
    await expectLater(
      cache.publish(
        temporary: await temporary(<int>[]),
        audioSha256: hashOf(<int>[]),
        container: 'wav',
      ),
      throwsA(isA<AudioCacheError>()),
    );
  });

  test(
    'R05: the same inputs producing different bytes do not overwrite',
    () async {
      // An OS voice update legitimately changes the output. The old file must
      // survive because a live resolution references its hash.
      final List<int> first = <int>[1, 1, 1];
      final List<int> second = <int>[2, 2, 2];
      final File a = await cache.publish(
        temporary: await temporary(first, 'one.part.wav'),
        audioSha256: hashOf(first),
        container: 'wav',
      );
      final File b = await cache.publish(
        temporary: await temporary(second, 'two.part.wav'),
        audioSha256: hashOf(second),
        container: 'wav',
      );

      expect(a.path, isNot(b.path));
      expect(
        a.existsSync(),
        isTrue,
        reason: 'the referenced file must survive',
      );
      expect(b.existsSync(), isTrue);
    },
  );

  test('publishing the same bytes twice keeps one file', () async {
    final List<int> bytes = <int>[9, 9, 9];
    final File a = await cache.publish(
      temporary: await temporary(bytes, 'x.part.wav'),
      audioSha256: hashOf(bytes),
      container: 'wav',
    );
    final File b = await cache.publish(
      temporary: await temporary(bytes, 'y.part.wav'),
      audioSha256: hashOf(bytes),
      container: 'wav',
    );
    expect(a.path, b.path);
  });

  test('a corrupted file fails verification and is deleted', () async {
    final List<int> bytes = <int>[4, 5, 6];
    final String digest = hashOf(bytes);
    final File published = await cache.publish(
      temporary: await temporary(bytes),
      audioSha256: digest,
      container: 'wav',
    );
    expect(await cache.verify(digest, 'wav'), isTrue);

    // Something modified the file underneath us.
    await published.writeAsBytes(<int>[0, 0, 0]);
    expect(
      await cache.verify(digest, 'wav'),
      isFalse,
      reason: 'corrupt bytes must never be played',
    );
    expect(published.existsSync(), isFalse, reason: 'and must be deleted');
  });

  test('a partial file left by a crash is swept', () async {
    await temporary(<int>[1], 'tts_abc.7.part.wav');
    await temporary(<int>[1], 'tts_def.8.part.caf');
    final List<int> good = <int>[3, 3];
    await cache.publish(
      temporary: await temporary(good, 'keep.part.wav'),
      audioSha256: hashOf(good),
      container: 'wav',
    );

    expect(await cache.sweepPartials(), 2);
    expect(await cache.verify(hashOf(good), 'wav'), isTrue);
  });

  group('eviction', () {
    Future<String> put(List<int> bytes) async {
      final String digest = hashOf(bytes);
      await cache.publish(
        temporary: await temporary(bytes, '${digest.substring(0, 6)}.part.wav'),
        audioSha256: digest,
        container: 'wav',
      );
      return digest;
    }

    test('nothing is evicted under the cap', () async {
      await put(<int>[1, 1]);
      await put(<int>[2, 2]);
      final EvictionOutcome outcome = await cache.evictToCap();
      expect(outcome.evicted, isEmpty);
      expect(outcome.overCap, isFalse);
    });

    test('R05: a pinned file is never evicted, even over the cap', () async {
      final String pinnedHash = await put(List<int>.filled(4096, 1));
      final String coldHash = await put(List<int>.filled(4096, 2));
      cache.pin(<String>[pinnedHash]);

      // A cap far below what is held, so eviction must do something.
      final EvictionOutcome outcome = await cache.evictToCap(capBytes: 100);
      expect(outcome.evicted, contains(coldHash));
      expect(outcome.evicted, isNot(contains(pinnedHash)));
      expect(await cache.verify(pinnedHash, 'wav'), isTrue);
      // And it says so rather than pretending it met the cap.
      expect(outcome.overCap, isTrue);
    });

    test('pins can be released when a run ends', () async {
      final String hash = await put(<int>[7, 7]);
      cache.pin(<String>[hash]);
      expect(cache.isPinned(hash), isTrue);
      cache.unpin(<String>[hash]);
      expect(cache.isPinned(hash), isFalse);

      final EvictionOutcome outcome = await cache.evictToCap(capBytes: 0);
      expect(outcome.evicted, contains(hash));
    });
  });

  test('the cap is stated in bytes, so MB and MiB cannot be confused', () {
    expect(AudioCache.softCapBytes, 150000000);
  });
}
