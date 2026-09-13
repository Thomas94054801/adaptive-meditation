import 'dart:async';

import 'audio_session.dart';

/// The audio session used until a platform plugin is wired in.
///
/// It grants focus, reports an unknown route and never interrupts. That is
/// honest about what it does rather than pretending to manage focus it does not
/// have: the player's behaviour under interruption is fully tested against a
/// controllable fake, and this is what ships until the plugin exists.
class SilentAudioSession implements AudioSessionPort {
  SilentAudioSession();

  final StreamController<AudioInterruption> _interruptions =
      StreamController<AudioInterruption>.broadcast();
  final StreamController<void> _focus = StreamController<void>.broadcast();
  final StreamController<AudioRoute> _routes =
      StreamController<AudioRoute>.broadcast();

  @override
  Future<bool> activate() async => true;

  @override
  Future<void> deactivate() async {}

  @override
  Future<AudioRoute> currentRoute() async => AudioRoute.unknown;

  @override
  Stream<AudioInterruption> get interruptions => _interruptions.stream;

  @override
  Stream<void> get focusRegained => _focus.stream;

  @override
  Stream<AudioRoute> get routeChanges => _routes.stream;

  Future<void> dispose() async {
    await _interruptions.close();
    await _focus.close();
    await _routes.close();
  }
}
