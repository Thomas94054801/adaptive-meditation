import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/config.dart';
import '../core/guest.dart';
import '../features/history/history_store.dart';
import '../features/welcome/welcome_screen.dart';
import '../platform/providers.dart';
import 'app_scope.dart';
import 'theme.dart';

class AdaptiveMeditationApp extends StatelessWidget {
  AdaptiveMeditationApp({MeditationApi? api, PlatformAdapters? adapters, super.key})
    : _adapters = adapters ?? PlatformAdapters(storage: PreferencesStorageProvider()),
      _api = api,
      _guestOverride = null;

  final MeditationApi? _api;
  final PlatformAdapters _adapters;
  final GuestIdentity? _guestOverride;

  @override
  Widget build(BuildContext context) {
    final GuestIdentity guest =
        _guestOverride ?? GuestIdentity(_adapters.storage);
    return AppScope(
      api:
          _api ??
          HttpMeditationApi(
            config: AppConfig.fromEnvironment(),
            guest: guest,
          ),
      guest: guest,
      history: SessionHistoryStore(),
      adapters: _adapters,
      child: MaterialApp(
        title: 'Adaptive Meditation',
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        home: const WelcomeScreen(),
      ),
    );
  }
}
