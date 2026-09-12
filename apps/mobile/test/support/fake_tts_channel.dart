import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Stands in for the platform TTS engine at the method-channel boundary.
///
/// This is not a fake `TtsProvider`. The adapter under test is the real one,
/// making real `MethodChannel` calls; only the operating system is replaced.
/// That is the difference between asserting a class name and asserting that
/// the platform is actually invoked with the right arguments.
class FakeTtsChannel {
  FakeTtsChannel({this.writeFile = true, this.acceptRequest = true});

  static const MethodChannel channel = MethodChannel('flutter_tts');

  /// Whether the "engine" writes an output file. False reproduces the engine
  /// that reports success and produces nothing.
  bool writeFile;

  /// Whether synthesizeToFile returns 1. False reproduces a refusal.
  bool acceptRequest;

  /// Bytes the "engine" writes. Empty reproduces a zero-length file.
  List<int> bytes = List<int>.filled(2048, 7);

  /// Never fire the completion handler, to reproduce a hung engine.
  bool reportCompletion = true;

  /// Fire an error instead of completion.
  String? failWith;

  /// Delay before the completion callback, so cancellation can be exercised.
  Duration completionDelay = Duration.zero;

  Directory? outputDirectory;

  final List<String> calls = <String>[];
  final Map<String, Object?> lastArguments = <String, Object?>{};

  void install() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, _handle);
  }

  void remove() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  }

  Future<Object?> _handle(MethodCall call) async {
    calls.add(call.method);
    if (call.arguments != null) {
      lastArguments[call.method] = call.arguments;
    }

    switch (call.method) {
      case 'synthesizeToFile':
        if (!acceptRequest) {
          return 0;
        }
        final Map<Object?, Object?> args =
            call.arguments as Map<Object?, Object?>;
        final String fileName = args['fileName']! as String;
        if (writeFile) {
          final Directory directory = outputDirectory!;
          await File('${directory.path}/$fileName').writeAsBytes(bytes);
        }
        // The platform answers "accepted" here. Completion arrives later,
        // separately - which is exactly the distinction a naive adapter
        // collapses.
        _scheduleCompletion();
        return 1;
      case 'getDefaultEngine':
        return 'com.example.tts';
      case 'getDefaultVoice':
        return <String, String>{'name': 'test-voice', 'locale': 'en-US'};
      default:
        return 1;
    }
  }

  void _scheduleCompletion() {
    Future<void>.delayed(completionDelay, () async {
      final String? error = failWith;
      if (error != null) {
        await _invokeApp('synth.onError', error);
        return;
      }
      if (reportCompletion) {
        await _invokeApp('synth.onComplete', null);
      }
    });
  }

  Future<void> _invokeApp(String method, Object? arguments) async {
    await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .handlePlatformMessage(
          channel.name,
          channel.codec.encodeMethodCall(MethodCall(method, arguments)),
          (_) {},
        );
  }
}
