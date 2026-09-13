import 'dart:async';

import 'package:audio_session/audio_session.dart' as plugin;

import 'audio_session.dart';

/// The real platform audio session.
///
/// This class is the single owner of focus and of the session category. The
/// player is constructed with `handleAudioSessionActivation: false` precisely
/// so that there is one owner rather than two overwriting each other, and the
/// TTS engine is configured after this, never before.
///
/// The one behaviour worth stating plainly: focus returning does **not** resume
/// playback. It emits on [focusRegained] so the UI can offer the choice, and
/// nothing else happens. A voice starting the moment a phone call ends is the
/// single worst thing a meditation app can do.
class NativeAudioSession implements AudioSessionPort {
  NativeAudioSession();

  plugin.AudioSession? _session;
  final StreamController<AudioInterruption> _interruptions =
      StreamController<AudioInterruption>.broadcast();
  final StreamController<void> _focus = StreamController<void>.broadcast();
  final StreamController<AudioRoute> _routes =
      StreamController<AudioRoute>.broadcast();

  StreamSubscription<plugin.AudioInterruptionEvent>? _interruptionSub;
  StreamSubscription<void>? _noisySub;
  StreamSubscription<plugin.AudioDevicesChangedEvent>? _devicesSub;

  bool _configured = false;
  AudioRoute _lastRoute = AudioRoute.unknown;

  /// Configure once, after every plugin is loaded, so nothing overwrites it.
  Future<plugin.AudioSession> _ensure() async {
    final plugin.AudioSession? existing = _session;
    if (existing != null && _configured) {
      return existing;
    }
    final plugin.AudioSession session =
        existing ?? await plugin.AudioSession.instance;
    _session = session;

    // Speech playback, spoken-audio hints, and no mixing: a meditation is not
    // background music and should not duck under something else.
    await session.configure(
      const plugin.AudioSessionConfiguration(
        avAudioSessionCategory: plugin.AVAudioSessionCategory.playback,
        avAudioSessionMode: plugin.AVAudioSessionMode.spokenAudio,
        avAudioSessionCategoryOptions:
            plugin.AVAudioSessionCategoryOptions.none,
        avAudioSessionRouteSharingPolicy:
            plugin.AVAudioSessionRouteSharingPolicy.defaultPolicy,
        avAudioSessionSetActiveOptions:
            plugin.AVAudioSessionSetActiveOptions.none,
        androidAudioAttributes: plugin.AndroidAudioAttributes(
          contentType: plugin.AndroidAudioContentType.speech,
          usage: plugin.AndroidAudioUsage.media,
        ),
        androidAudioFocusGainType: plugin.AndroidAudioFocusGainType.gain,
        androidWillPauseWhenDucked: true,
      ),
    );

    _interruptionSub ??= session.interruptionEventStream.listen(
      _onInterruption,
    );
    // Headphones pulled out. The platform tells us before the sound would
    // reach the speaker, which is the whole value of this event.
    _noisySub ??= session.becomingNoisyEventStream.listen((_) {
      _lastRoute = AudioRoute.speaker;
      _interruptions.add(AudioInterruption.wentPublic);
      _routes.add(AudioRoute.speaker);
    });
    _devicesSub ??= session.devicesChangedEventStream.listen(_onDevicesChanged);

    _configured = true;
    return session;
  }

  void _onInterruption(plugin.AudioInterruptionEvent event) {
    if (event.begin) {
      _interruptions.add(AudioInterruption.focusLost);
      return;
    }
    // Ended. Emitted so the UI can offer resume; playback stays paused
    // whatever `event.type` suggests we are permitted to do.
    _focus.add(null);
  }

  void _onDevicesChanged(plugin.AudioDevicesChangedEvent event) {
    final AudioRoute previous = _lastRoute;
    final AudioRoute current = _routeFrom(
      event.devicesAdded.isNotEmpty
          ? event.devicesAdded
          : <plugin.AudioDevice>{},
    );
    if (current == AudioRoute.unknown && event.devicesRemoved.isEmpty) {
      return;
    }
    _lastRoute = current;
    _routes.add(current);
    final AudioInterruption? decision = interruptionForRouteChange(
      previous,
      current,
    );
    if (decision != null) {
      _interruptions.add(decision);
    }
  }

  /// Map a device set to our coarse route.
  ///
  /// Matched on the enum's *name* rather than its constants on purpose.
  /// `AudioDeviceType` is marked experimental in audio_session 0.2.4 and its
  /// members differ from what the platform docs suggest - `usbHeadset` does
  /// not exist there at all. Binding to names means a plugin upgrade that adds
  /// or renames a device type degrades to `unknown`, which §5.3's rule already
  /// treats as audible-to-the-room, instead of failing to compile or silently
  /// mis-classifying. The event this class actually depends on for the privacy
  /// rule is `becomingNoisyEventStream`, which is stable.
  AudioRoute _routeFrom(Set<plugin.AudioDevice> devices) {
    for (final plugin.AudioDevice device in devices) {
      final String name = device.type.name.toLowerCase();
      if (name.contains('headset') || name.contains('headphone')) {
        return AudioRoute.headphones;
      }
      if (name.contains('bluetooth')) {
        return AudioRoute.bluetooth;
      }
      if (name.contains('speaker')) {
        return AudioRoute.speaker;
      }
      if (name.contains('earpiece')) {
        return AudioRoute.receiver;
      }
      if (name.contains('airplay')) {
        return AudioRoute.airplay;
      }
    }
    return AudioRoute.unknown;
  }

  @override
  Future<bool> activate() async {
    final plugin.AudioSession session = await _ensure();
    // False means another app holds focus. The caller must not play.
    return session.setActive(true);
  }

  @override
  Future<void> deactivate() async {
    final plugin.AudioSession? session = _session;
    if (session != null) {
      await session.setActive(false);
    }
  }

  @override
  Future<AudioRoute> currentRoute() async {
    final plugin.AudioSession session = await _ensure();
    final Set<plugin.AudioDevice> devices = await session.getDevices();
    final AudioRoute route = _routeFrom(devices);
    _lastRoute = route;
    return route;
  }

  @override
  Stream<AudioInterruption> get interruptions => _interruptions.stream;

  @override
  Stream<void> get focusRegained => _focus.stream;

  @override
  Stream<AudioRoute> get routeChanges => _routes.stream;

  /// Configure without claiming focus. Called during bootstrap so the session
  /// category is set before the TTS engine can touch it.
  Future<void> warmUp() async {
    await _ensure();
  }

  Future<void> dispose() async {
    await _interruptionSub?.cancel();
    await _noisySub?.cancel();
    await _devicesSub?.cancel();
    await _interruptions.close();
    await _focus.close();
    await _routes.close();
  }
}
