import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';

/// The on-device audio store — SDD A4.
///
/// Two rules shape this class.
///
/// **Outputs are immutable.** A `render_key` indexes inputs; the file is named
/// by the hash of its own bytes. The same text synthesised twice after an OS
/// voice update legitimately produces different bytes, and that must not
/// overwrite a file a live resolution still references. So a key maps to one or
/// more verified outputs, and a resolution binds a specific `audio_sha256`.
///
/// **The database and the filesystem are not one transaction.** Every write is
/// temporary file → flush → verify → atomic rename. A crash can therefore leave
/// a `.part` file, which start-up sweeps, but never a file that is named as
/// finished while being half-written.
class AudioCache {
  AudioCache({required Directory root}) : _root = root;

  final Directory _root;

  /// Keys whose files must survive eviction: a run that is preparing, ready,
  /// playing, paused, interrupted, or promised as resumable.
  final Set<String> _pinned = <String>{};

  Directory get root => _root;

  /// Soft cap, in bytes. The SDD's 150 MB contract, stated in bytes so nobody
  /// has to guess whether it meant MB or MiB.
  static const int softCapBytes = 150000000;

  static const Duration staleAfter = Duration(days: 90);

  Future<void> ensureReady() async {
    if (!await _root.exists()) {
      await _root.create(recursive: true);
    }
  }

  /// Where a verified output lives. Named by its own content.
  File fileFor(String audioSha256, String container) =>
      File('${_root.path}/$audioSha256.$container');

  /// Publish synthesised bytes atomically.
  ///
  /// Verifies before renaming, so a file that exists under its final name has
  /// always been checked. Returns the published file.
  Future<File> publish({
    required File temporary,
    required String audioSha256,
    required String container,
  }) async {
    await ensureReady();
    final List<int> bytes = await temporary.readAsBytes();
    if (bytes.isEmpty) {
      await temporary.delete();
      throw const AudioCacheError('refusing to publish an empty file');
    }
    final String actual = sha256.convert(bytes).toString();
    if (actual != audioSha256) {
      await temporary.delete();
      throw AudioCacheError(
        'hash mismatch before publish: expected $audioSha256, got $actual',
      );
    }

    final File destination = fileFor(audioSha256, container);
    if (await destination.exists()) {
      // Content-addressed, so an existing file with this name has the same
      // bytes by construction. Keep it and drop the duplicate work.
      await temporary.delete();
      return destination;
    }
    // Rename is atomic within a filesystem: no reader can observe a partial
    // file under the final name.
    final File published = await temporary.rename(destination.path);
    return published;
  }

  /// Verify a file still matches the hash a resolution references.
  ///
  /// A mismatch means the entry is corrupt. It is deleted and re-synthesised,
  /// never played: a corrupt file becoming a sound in the middle of a
  /// meditation is the worst possible moment to find out.
  Future<bool> verify(String audioSha256, String container) async {
    final File file = fileFor(audioSha256, container);
    if (!await file.exists()) {
      return false;
    }
    final List<int> bytes = await file.readAsBytes();
    if (bytes.isEmpty) {
      await file.delete();
      return false;
    }
    if (sha256.convert(bytes).toString() != audioSha256) {
      await file.delete();
      return false;
    }
    return true;
  }

  void pin(Iterable<String> audioHashes) => _pinned.addAll(audioHashes);

  void unpin(Iterable<String> audioHashes) => _pinned.removeAll(audioHashes);

  Set<String> get pinned => Set<String>.unmodifiable(_pinned);

  bool isPinned(String audioSha256) => _pinned.contains(audioSha256);

  /// Remove leftovers from an interrupted prepare.
  ///
  /// Run at start-up. A `.part` file is work that was in flight when the
  /// process died; nothing references it, because a reference is only written
  /// after publication.
  Future<int> sweepPartials() async {
    await ensureReady();
    int removed = 0;
    await for (final FileSystemEntity entry in _root.list()) {
      if (entry is File && entry.path.contains('.part')) {
        await entry.delete();
        removed++;
      }
    }
    return removed;
  }

  /// Total bytes held.
  Future<int> sizeInBytes() async {
    await ensureReady();
    int total = 0;
    await for (final FileSystemEntity entry in _root.list()) {
      if (entry is File) {
        total += await entry.length();
      }
    }
    return total;
  }

  /// Evict unpinned files, oldest-accessed first, until under the cap.
  ///
  /// A pinned file is never evicted, even if that leaves the cache over its
  /// cap: dropping the audio a paused session still needs trades a little disk
  /// for a broken meditation. [EvictionOutcome.overCap] reports that honestly
  /// rather than silently exceeding the limit.
  Future<EvictionOutcome> evictToCap({int capBytes = softCapBytes}) async {
    await ensureReady();
    final List<_Entry> entries = <_Entry>[];
    await for (final FileSystemEntity entry in _root.list()) {
      if (entry is! File) {
        continue;
      }
      final FileStat stat = await entry.stat();
      entries.add(
        _Entry(
          file: entry,
          bytes: stat.size,
          accessed: stat.accessed,
          hash: _hashFromPath(entry.path),
        ),
      );
    }

    int total = entries.fold<int>(0, (int sum, _Entry e) => sum + e.bytes);
    final List<String> evicted = <String>[];
    final DateTime now = DateTime.now();

    // Stale first, regardless of pressure: ninety days without a read means
    // the corpus moved on.
    for (final _Entry entry in entries) {
      if (_pinned.contains(entry.hash)) {
        continue;
      }
      if (now.difference(entry.accessed) >= staleAfter) {
        await entry.file.delete();
        evicted.add(entry.hash);
        total -= entry.bytes;
      }
    }

    final List<_Entry> remaining =
        entries.where((_Entry e) => !evicted.contains(e.hash)).toList()
          ..sort((_Entry a, _Entry b) => a.accessed.compareTo(b.accessed));

    for (final _Entry entry in remaining) {
      if (total <= capBytes) {
        break;
      }
      if (_pinned.contains(entry.hash)) {
        continue;
      }
      await entry.file.delete();
      evicted.add(entry.hash);
      total -= entry.bytes;
    }

    return EvictionOutcome(
      evicted: evicted,
      retainedBytes: total,
      overCap: total > capBytes,
    );
  }

  String _hashFromPath(String path) {
    final String name = path.split(Platform.pathSeparator).last;
    final int dot = name.indexOf('.');
    return dot < 0 ? name : name.substring(0, dot);
  }
}

class _Entry {
  const _Entry({
    required this.file,
    required this.bytes,
    required this.accessed,
    required this.hash,
  });

  final File file;
  final int bytes;
  final DateTime accessed;
  final String hash;
}

class EvictionOutcome {
  const EvictionOutcome({
    required this.evicted,
    required this.retainedBytes,
    required this.overCap,
  });

  final List<String> evicted;
  final int retainedBytes;

  /// True when the cap could not be met without evicting a pinned file. An
  /// honest over-cap beats a broken session.
  final bool overCap;
}

class AudioCacheError implements Exception {
  const AudioCacheError(this.message);
  final String message;
  @override
  String toString() => 'AudioCacheError: $message';
}
