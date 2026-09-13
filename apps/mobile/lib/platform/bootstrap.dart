import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../core/durable_store.dart';

import 'audio_player_port.dart';
import 'native_audio_player.dart';
import 'native_audio_session.dart';
import 'native_tts_provider.dart';
import 'providers.dart';
import 'secure_identity_store.dart';

/// How the app is assembled in production.
///
/// Order matters and is the reason this is a function rather than a set of
/// defaults on [PlatformAdapters]. The audio session is configured **first**,
/// before the TTS engine is touched, because whichever of the two configures
/// last wins on iOS — and a session left in a speech-synthesis configuration
/// plays a meditation through the earpiece.
class AudioRuntimeAdapters {
  const AudioRuntimeAdapters({
    required this.adapters,
    required this.player,
    required this.session,
    required this.tts,
    required this.mediaDirectory,
    required this.store,
  });

  final PlatformAdapters adapters;
  final AudioPlayerPort player;
  final NativeAudioSession session;
  final NativeTtsProvider tts;

  /// Where synthesised audio is written. Application support, not cache: the
  /// OS may clear a cache directory between launches, and a prepared session
  /// must survive to be resumable.
  final Directory mediaDirectory;

  /// The durable local store, opened at bootstrap so a failure to open it is
  /// visible at start-up rather than at the moment a user saves feedback.
  final DurableStore store;
}

/// Build the production adapter set. Called once, from `main`.
Future<AudioRuntimeAdapters> bootstrapAudioRuntime({
  SecureIdentityStore? identityStore,
}) async {
  final SecureIdentityStore store =
      identityStore ?? PlatformSecureIdentityStore();

  final Directory support = await getApplicationSupportDirectory();
  final Directory media = Directory('${support.path}/audio');
  if (!await media.exists()) {
    await media.create(recursive: true);
  }

  // 1. Session first, so the category is ours.
  final NativeAudioSession session = NativeAudioSession();
  await session.warmUp();

  // 2. Then the synthesiser, which must not reconfigure the session.
  final NativeTtsProvider tts = NativeTtsProvider()..useOutputDirectory(media);

  // 3. Then the player, which owns neither interruptions nor activation.
  final AudioPlayerPort player = NativeAudioPlayer();

  // 4. The durable store. Application support rather than cache, for the same
  // reason as the audio: the OS may clear a cache directory and a queued
  // operation is the only copy that exists.
  final Database database = await openDatabase(
    '${support.path}/program004r.db',
    version: DurableStore.schemaVersion,
    onCreate: (Database db, int version) =>
        DurableStore.migrate(db, 0, version),
    onUpgrade: DurableStore.migrate,
  );
  final DurableStore durableStore = DurableStore(database: database);

  return AudioRuntimeAdapters(
    adapters: PlatformAdapters(
      tts: tts,
      audioSession: session,
      storage: SecureStorageProviderAdapter(store),
    ),
    player: player,
    session: session,
    tts: tts,
    mediaDirectory: media,
    store: durableStore,
  );
}

/// Names that must never appear in a production adapter set.
///
/// The check is by runtime type rather than by a flag on the class, because a
/// flag is something a stub can lie about. A test double reaching production
/// is the defect Program004 shipped: the app injected a silent no-op provider
/// and every session was a silent countdown that still reported completion.
const Set<String> forbiddenProductionAdapterTypes = <String>{
  'SilentAudioSession',
  'UnavailableTtsProvider',
  'FakeAudioSession',
  'FakeTtsProvider',
  'FakeAudioPlayer',
  'FakeMeditationApi',
};

/// Whether an adapter set is fit to ship.
///
/// Returns the offending type names, empty when the set is clean.
List<String> auditProductionAdapters({
  required PlatformAdapters adapters,
  required AudioPlayerPort player,
}) {
  final List<String> offenders = <String>[];
  void check(Object candidate) {
    final String name = candidate.runtimeType.toString();
    if (forbiddenProductionAdapterTypes.contains(name)) {
      offenders.add(name);
    }
  }

  check(adapters.tts);
  check(adapters.audioSession);
  check(player);
  return offenders;
}
