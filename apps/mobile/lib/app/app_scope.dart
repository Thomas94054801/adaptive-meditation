import 'package:flutter/widgets.dart';

import '../core/api.dart';
import '../core/guest.dart';
import '../features/history/history_store.dart';
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
  });

  final MeditationApi api;
  final GuestIdentity guest;

  /// Retained for the current run's list while a screen is open. The durable
  /// record now lives on the backend and is read through [api].
  final SessionHistoryStore history;
  final PlatformAdapters adapters;

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
      adapters != oldWidget.adapters;
}
