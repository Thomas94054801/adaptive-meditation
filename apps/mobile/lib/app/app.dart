import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/config.dart';
import '../features/history/history_store.dart';
import '../features/welcome/welcome_screen.dart';
import '../platform/providers.dart';
import 'app_scope.dart';
import 'theme.dart';

class AdaptiveMeditationApp extends StatelessWidget {
  AdaptiveMeditationApp({MeditationApi? api, super.key})
    : _api = api ?? HttpMeditationApi(config: AppConfig.fromEnvironment());

  final MeditationApi _api;

  @override
  Widget build(BuildContext context) {
    return AppScope(
      api: _api,
      history: SessionHistoryStore(),
      adapters: PlatformAdapters(),
      child: MaterialApp(
        title: 'Adaptive Meditation',
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        home: const WelcomeScreen(),
      ),
    );
  }
}
