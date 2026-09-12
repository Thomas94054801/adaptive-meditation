import 'package:flutter/material.dart';

import 'app/app.dart';
import 'platform/bootstrap.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Built here, not lazily inside the widget tree, because the audio session
  // must be configured before anything else touches audio and because a
  // failure to build the real adapters must be visible rather than silently
  // replaced by something that makes no sound.
  final AudioRuntimeAdapters runtime = await bootstrapAudioRuntime();

  runApp(
    AdaptiveMeditationApp(
      adapters: runtime.adapters,
      player: runtime.player,
      mediaDirectory: runtime.mediaDirectory,
    ),
  );
}
