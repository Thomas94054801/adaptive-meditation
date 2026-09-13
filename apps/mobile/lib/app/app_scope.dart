import 'dart:io';

import 'package:flutter/widgets.dart';

import '../core/api.dart';
import '../core/durable_store.dart';
import '../core/guest.dart';
import '../features/history/history_store.dart';
import '../platform/audio_player_port.dart';
import '../platform/providers.dart';

/// Dependencies shared by the screens.
///
/// Plain InheritedWidget rather than a state-management package: Program001 has
/// one linear flow and no cross-screen state to synchronise.
class AppScope extends InheritedWidget {
  const AppScope({
    required this.api,
    required this.guest,
    required this.history,
    required this.adapters,
    required super.child,
    super.key,
    this.player,
    this.mediaDirectory,
    this.store,
  });

  final MeditationApi api;
  final GuestIdentity guest;

  /// Retained for the current run's list while a screen is open. The durable
  /// record now lives on the backend and is read through [api].
  final SessionHistoryStore history;
  final PlatformAdapters adapters;

  /// The platform player. Null in widget tests that never play anything, and
  /// in that case the player screen refuses to claim an audible session rather
  /// than pretending with a timer.
  final AudioPlayerPort? player;

  /// Where prepared audio is written. Null when nothing will be prepared.
  final Directory? mediaDirectory;

  /// The durable local store. Null in widget tests that assert nothing about
  /// persistence; those keep the pre-Program004R behaviour of posting straight
  /// to the backend.
  final DurableStore? store;

  static AppScope of(BuildContext context) {
    final AppScope? scope = context
        .dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'AppScope is missing from the widget tree');
    return scope!;
  }

  @override
  bool updateShouldNotify(AppScope oldWidget) =>
      api != oldWidget.api ||
      guest != oldWidget.guest ||
      history != oldWidget.history ||
      adapters != oldWidget.adapters ||
      player != oldWidget.player ||
      mediaDirectory != oldWidget.mediaDirectory ||
      store != oldWidget.store;
}
