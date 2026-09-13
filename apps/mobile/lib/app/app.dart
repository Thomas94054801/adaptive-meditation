import 'dart:io';

import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/config.dart';
import '../core/durable_store.dart';
import '../core/guest.dart';
import '../features/history/history_store.dart';
import '../features/welcome/welcome_screen.dart';
import '../platform/audio_player_port.dart';
import '../platform/providers.dart';
import '../platform/secure_identity_store.dart';
import 'app_scope.dart';
import 'theme.dart';

class AdaptiveMeditationApp extends StatelessWidget {
  AdaptiveMeditationApp({
    MeditationApi? api,
    PlatformAdapters? adapters,
    SecureIdentityStore? identityStore,
    AudioPlayerPort? player,
    Directory? mediaDirectory,
    DurableStore? store,
    super.key,
  }) : _identityStore = identityStore ?? PlatformSecureIdentityStore(),
       _api = api,
       _adaptersOverride = adapters,
       _player = player,
       _mediaDirectory = mediaDirectory,
       _store = store;

  final MeditationApi? _api;
  final PlatformAdapters? _adaptersOverride;
  final SecureIdentityStore _identityStore;
  final AudioPlayerPort? _player;
  final Directory? _mediaDirectory;
  final DurableStore? _store;

  @override
  Widget build(BuildContext context) {
    final GuestIdentity guest = GuestIdentity(_identityStore);
    final PlatformAdapters adapters =
        _adaptersOverride ??
        PlatformAdapters(storage: SecureStorageProviderAdapter(_identityStore));
    return AppScope(
      api:
          _api ??
          HttpMeditationApi(config: AppConfig.fromEnvironment(), guest: guest),
      guest: guest,
      history: SessionHistoryStore(),
      adapters: adapters,
      player: _player,
      mediaDirectory: _mediaDirectory,
      store: _store,
      child: MaterialApp(
        title: 'Adaptive Meditation',
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        home: const WelcomeScreen(),
      ),
    );
  }
}
