import 'dart:io';

import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/config.dart';
import '../core/deletion.dart';
import '../core/durable_store.dart';
import '../core/guest.dart';
import '../core/preferences.dart';
import '../core/reminders.dart';
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
        home: const _StartResumeHooks(child: WelcomeScreen()),
      ),
    );
  }
}

/// Program005 SDD sections 9.1 and 9.5: at start and on every resume, finish
/// a deletion a previous run left unconfirmed, then make the OS reminder
/// agree with the preference. Both are idempotent and neither prompts. No
/// timer, no polling: the lifecycle is the only trigger.
class _StartResumeHooks extends StatefulWidget {
  const _StartResumeHooks({required this.child});

  final Widget child;

  @override
  State<_StartResumeHooks> createState() => _StartResumeHooksState();
}

class _StartResumeHooksState extends State<_StartResumeHooks>
    with WidgetsBindingObserver {
  bool _ran = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_ran) {
      _ran = true;
      _reconcile();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _reconcile();
    }
  }

  Future<void> _reconcile() async {
    final AppScope scope = AppScope.of(context);
    final DurableStore? store = scope.store;
    if (store == null) {
      return;
    }
    try {
      await DeletionProcedure(
        api: scope.api,
        store: store,
        notifications: scope.adapters.notifications,
        guest: scope.guest,
      ).resumeIfPending();
      await ReminderController(
        notifications: scope.adapters.notifications,
        preferences: Preferences(store),
      ).reconcile();
    } catch (_) {
      // Start and resume must never fail the app over a reminder; the
      // settings screen reports the state when the person looks.
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
