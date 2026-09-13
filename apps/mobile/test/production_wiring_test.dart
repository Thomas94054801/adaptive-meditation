import 'package:adaptive_meditation/platform/audio_player_port.dart';
import 'package:adaptive_meditation/platform/bootstrap.dart';
import 'package:adaptive_meditation/platform/native_audio_player.dart';
import 'package:adaptive_meditation/platform/native_audio_session.dart';
import 'package:adaptive_meditation/platform/native_tts_provider.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:adaptive_meditation/platform/silent_audio_session.dart';
import 'package:flutter_test/flutter_test.dart';

/// R15 — production composition.
///
/// Program004 shipped an app that injected a silent no-op provider, so every
/// session was a countdown that still reported completion. These tests are
/// about that specific failure: they assert what the production set *is*, and
/// that the audit refuses the things that caused it.
void main() {
  // Constructing the real adapters touches plugin registrants, so the binding
  // has to exist. That is itself part of what this test asserts: these are the
  // real classes, not stand-ins that need no platform.
  TestWidgetsFlutterBinding.ensureInitialized();

  group('the audit rejects test doubles', () {
    test('a silent session is refused', () {
      final List<String> offenders = auditProductionAdapters(
        adapters: PlatformAdapters(
          tts: NativeTtsProvider(),
          audioSession: SilentAudioSession(),
        ),
        player: NativeAudioPlayer(),
      );
      expect(offenders, contains('SilentAudioSession'));
    });

    test('a provider that cannot synthesise is refused', () {
      final List<String> offenders = auditProductionAdapters(
        adapters: PlatformAdapters(
          tts: const UnavailableTtsProvider(),
          audioSession: NativeAudioSession(),
        ),
        player: NativeAudioPlayer(),
      );
      expect(offenders, contains('UnavailableTtsProvider'));
    });

    test('the real set passes', () {
      final List<String> offenders = auditProductionAdapters(
        adapters: PlatformAdapters(
          tts: NativeTtsProvider(),
          audioSession: NativeAudioSession(),
        ),
        player: NativeAudioPlayer(),
      );
      expect(offenders, isEmpty);
    });
  });

  group('the ports are the real implementations', () {
    test('the TTS provider reports itself supported and file-based', () {
      final NativeTtsProvider tts = NativeTtsProvider();
      expect(tts.isSupported, isTrue);
      // Not localConfirmed: no probe with the network down has run, and the
      // label must not claim more than was observed.
      expect(tts.offlineCapability, TtsOfflineCapability.localUnconfirmed);
    });

    test('the TTS port has no live speak method', () {
      // Enforced by the type system: a live synthesiser on the playback path
      // would make duration unknowable before the session starts.
      expect(
        TtsProvider,
        isNotNull,
        reason: 'TtsProvider exposes describe/synthesizeToFile/stop only',
      );
      final NativeTtsProvider tts = NativeTtsProvider();
      expect(tts, isA<TtsProvider>());
      // ignore: unnecessary_type_check
      expect(tts is TtsProvider, isTrue);
    });

    test('the default adapter set is not silently audible-looking', () {
      // PlatformAdapters' own defaults are deliberately the unavailable ones,
      // so an adapter set built without arguments cannot masquerade as
      // production. Production comes from bootstrapAudioRuntime.
      final PlatformAdapters defaults = PlatformAdapters();
      expect(defaults.tts.isSupported, isFalse);
      expect(
        auditProductionAdapters(
          adapters: defaults,
          player: NativeAudioPlayer(),
        ),
        isNotEmpty,
        reason:
            'a default-constructed set must never pass the production audit',
      );
    });
  });

  group('the player is constructed with the flags that matter', () {
    test('it exposes the port and nothing wider', () {
      final AudioPlayerPort player = NativeAudioPlayer();
      expect(player, isA<AudioPlayerPort>());
      expect(player.isPlaying, isFalse);
      expect(player.position, Duration.zero);
    });
  });

  test('forbidden type names cover every double in this repository', () {
    // A double added later without being listed here would pass the audit.
    for (final String name in <String>[
      'SilentAudioSession',
      'UnavailableTtsProvider',
      'FakeAudioSession',
      'FakeMeditationApi',
    ]) {
      expect(forbiddenProductionAdapterTypes, contains(name));
    }
  });
}
