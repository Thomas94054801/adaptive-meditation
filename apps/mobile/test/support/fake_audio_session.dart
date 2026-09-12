import 'dart:async';

import 'package:adaptive_meditation/platform/audio_session.dart';

/// An audio session a test can drive: grant or refuse focus, interrupt on cue.
class FakeAudioSession implements AudioSessionPort {
  FakeAudioSession({
    this.grantFocus = true,
    this.route = AudioRoute.headphones,
  });

  bool grantFocus;
  AudioRoute route;
  int activations = 0;
  int deactivations = 0;

  final StreamController<AudioInterruption> _interruptions =
      StreamController<AudioInterruption>.broadcast();
  final StreamController<void> _focus = StreamController<void>.broadcast();
  final StreamController<AudioRoute> _routes =
      StreamController<AudioRoute>.broadcast();

  @override
  Future<bool> activate() async {
    activations++;
    return grantFocus;
  }

  @override
  Future<void> deactivate() async {
    deactivations++;
  }

  @override
  Future<AudioRoute> currentRoute() async => route;

  @override
  Stream<AudioInterruption> get interruptions => _interruptions.stream;

  @override
  Stream<void> get focusRegained => _focus.stream;

  @override
  Stream<AudioRoute> get routeChanges => _routes.stream;

  void interrupt(AudioInterruption interruption) =>
      _interruptions.add(interruption);

  void regainFocus() => _focus.add(null);

  void changeRoute(AudioRoute next) {
    route = next;
    _routes.add(next);
  }

  Future<void> dispose() async {
    await _interruptions.close();
    await _focus.close();
    await _routes.close();
  }
}
