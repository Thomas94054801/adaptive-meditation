import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
import '../../core/models.dart';
import '../../platform/audio_session.dart';
import '../feedback/feedback_screen.dart';
import 'playback_controller.dart';
import 'transcript_sheet.dart';

/// The Program004 player.
///
/// The screen owns a ticker and nothing else. Position, state and legality all
/// come from [PlaybackController], which is pure, so what the player does under
/// an interruption or a bad clock reading is decided in code a test can drive
/// directly rather than in a widget nobody can pause.
///
/// Backend calls are best-effort. A meditation must not stop because a network
/// round trip failed: events queue and go with the next batch, and the run
/// state the server holds is reconciled on the next successful call.
class PlayerScreen extends StatefulWidget {
  const PlayerScreen({
    required this.session,
    required this.plan,
    required this.beforeState,
    super.key,
    this.autoStart = true,
    this.tickInterval = const Duration(milliseconds: 200),
  });

  final MeditationSession session;
  final SessionPlanV2 plan;
  final CheckIn beforeState;

  /// Disabled in widget tests so no timer outlives the test.
  final bool autoStart;

  final Duration tickInterval;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  late final PlaybackController _controller = PlaybackController(
    plan: widget.plan,
    commandIdFactory: _newCommandId,
  );

  final Stopwatch _monotonic = Stopwatch();
  Timer? _ticker;
  StreamSubscription<AudioInterruption>? _interruptions;
  StreamSubscription<void>? _focusRegained;
  String? _notice;
  int _commandCounter = 0;

  MeditationApi get _api => AppScope.of(context).api;

  @override
  void initState() {
    super.initState();
    if (widget.autoStart) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _prepareAndStart());
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // The audio session comes from an inherited widget, which cannot be read
    // during initState. Subscribing here, once, is the supported point.
    if (_interruptions == null) {
      _listenForInterruptions();
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _interruptions?.cancel();
    _focusRegained?.cancel();
    super.dispose();
  }

  String _newCommandId() {
    _commandCounter += 1;
    return '${widget.session.id}-$_commandCounter-'
        '${DateTime.now().microsecondsSinceEpoch}';
  }

  void _listenForInterruptions() {
    final AudioSessionPort session = AppScope.of(context).adapters.audioSession;
    _interruptions = session.interruptions.listen(_onInterruption);
    // Focus returning leaves the run paused on purpose. A voice starting the
    // moment a call ends is exactly what nobody wants.
    _focusRegained = session.focusRegained.listen((_) {
      _send(RunCommand.interruptionEnded);
      if (mounted) {
        setState(
          () => _notice = 'Paused while you were away. Resume when ready.',
        );
      }
    });
  }

  void _onInterruption(AudioInterruption interruption) {
    if (!_controller.can(RunCommand.interrupt)) {
      return;
    }
    _stopTicker();
    _send(RunCommand.interrupt);
    setState(
      () => _notice = switch (interruption) {
        AudioInterruption.focusLost => 'Paused - another app is using audio.',
        AudioInterruption.wentPublic =>
          'Paused - headphones disconnected, so audio would have played out loud.',
      },
    );
  }

  Future<void> _prepareAndStart() async {
    _send(RunCommand.prepare);
    try {
      await _api.prepareSession(widget.session.id);
    } on ApiException {
      // A manifest we could not fetch is not a reason to refuse to meditate.
      // Every segment simply falls to the device, or to its transcript.
    }
    _send(RunCommand.resolved);
    await _start();
  }

  Future<void> _start() async {
    final bool granted = await AppScope.of(
      context,
    ).adapters.audioSession.activate();
    if (!mounted) {
      return;
    }
    if (!granted) {
      setState(
        () => _notice = 'Another app is using audio. Stop it and press Resume.',
      );
      return;
    }
    _send(
      _controller.state == RunState.paused
          ? RunCommand.resume
          : RunCommand.start,
    );
    _startTicker();
    setState(() => _notice = null);
  }

  void _startTicker() {
    _monotonic.start();
    _ticker?.cancel();
    _ticker = Timer.periodic(widget.tickInterval, (_) => _tick());
  }

  void _stopTicker() {
    _ticker?.cancel();
    _ticker = null;
    _controller.tickTo(_monotonic.elapsedMilliseconds);
    _monotonic.stop();
  }

  void _tick() {
    setState(() => _controller.tickTo(_monotonic.elapsedMilliseconds));
    if (_controller.reachedEnd) {
      _complete();
    }
  }

  void _pause() {
    _stopTicker();
    _send(RunCommand.pause);
    setState(() => _notice = null);
  }

  Future<void> _complete() async {
    _stopTicker();
    _send(RunCommand.complete);
    await _flush();
    await _goToFeedback(completed: true);
  }

  Future<void> _end() async {
    _stopTicker();
    _send(RunCommand.abandon);
    await _flush();
    await _goToFeedback(completed: false);
  }

  /// Applies a command locally, then tells the backend. Local first, because
  /// the user pressing pause must see the session pause whatever the network
  /// is doing.
  void _send(RunCommand command) {
    final PlaybackEvent? event = _controller.apply(
      command,
      nowMs: _monotonic.elapsedMilliseconds,
    );
    if (event == null) {
      return;
    }
    unawaited(_deliver(command, event));
  }

  Future<void> _deliver(RunCommand command, PlaybackEvent event) async {
    try {
      final PlaybackState state = await _api.applyPlaybackCommand(
        sessionId: widget.session.id,
        command: command.wireValue,
        commandId: event.commandId!,
        sequence: event.sequence,
        elapsedMs: event.elapsedMs,
        segmentId: event.segmentId,
      );
      // The command's own journal entry is written server-side, so it does not
      // need sending again in the event batch.
      _controller.acknowledge(<PlaybackEvent>[event]);
      if (!state.applied && state.runState != _controller.state.wireValue) {
        // The server rejected it as a replay or an out-of-order arrival. It is
        // authoritative: adopting its view is how the two stop disagreeing.
        _adopt(state);
      }
    } on ApiException {
      // Keep it queued. The next batch carries it.
    }
  }

  void _adopt(PlaybackState state) {
    if (!mounted) {
      return;
    }
    setState(() {
      _controller.adopt(
        state: RunState.values.firstWhere(
          (RunState s) => s.wireValue == state.runState,
          orElse: () => _controller.state,
        ),
        positionMs: state.resumeOffsetMs > 0
            ? state.resumeOffsetMs
            : state.elapsedMs,
        sequence: state.commandSequence,
      );
    });
  }

  Future<void> _flush() async {
    final List<PlaybackEvent> pending = _controller.takePending();
    if (pending.isEmpty) {
      return;
    }
    try {
      await _api.appendEvents(
        widget.session.id,
        pending.map((PlaybackEvent e) => e.toJson()).toList(growable: false),
      );
      _controller.acknowledge(pending);
    } on ApiException {
      // Dropped rather than retried forever: the journal is an aid to
      // reconstruction, not something worth blocking a user's feedback screen.
    }
  }

  Future<void> _goToFeedback({required bool completed}) async {
    await AppScope.of(context).adapters.audioSession.deactivate();
    if (!mounted) {
      return;
    }
    await Navigator.of(context).pushReplacement<void, void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => FeedbackScreen(
          session: widget.session,
          beforeState: widget.beforeState,
          completed: completed,
          completionRatio: _controller.progress,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final TimelineSegment? line = _controller.visibleSpeech;
    final bool playing = _controller.isPlaying;
    final int remaining = _controller.remainingMs;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.plan.publicTitle),
        automaticallyImplyLeading: false,
        actions: <Widget>[
          IconButton(
            key: const Key('player_transcript'),
            icon: const Icon(Icons.subject),
            tooltip: 'Read the transcript',
            onPressed: () => TranscriptSheet.show(
              context,
              plan: widget.plan,
              currentSegmentId: line?.id,
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Semantics(
                label:
                    'Session progress, '
                    '${(_controller.progress * 100).round()} percent',
                child: LinearProgressIndicator(
                  key: const Key('player_progress'),
                  value: _controller.progress,
                  minHeight: 6,
                ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: <Widget>[
                  Text(
                    _controller.isInSilence ? 'Silence' : 'Guidance',
                    key: const Key('player_phase'),
                    style: theme.textTheme.labelLarge,
                  ),
                  Text(
                    formatDuration(remaining),
                    key: const Key('player_remaining'),
                    semanticsLabel:
                        '${remaining ~/ 60000} minutes '
                        '${(remaining ~/ 1000) % 60} seconds remaining',
                    style: theme.textTheme.labelLarge,
                  ),
                ],
              ),
              if (_notice != null) ...<Widget>[
                const SizedBox(height: 12),
                Text(
                  _notice!,
                  key: const Key('player_notice'),
                  style: theme.textTheme.bodyMedium,
                ),
              ],
              const SizedBox(height: 32),
              Expanded(
                child: Center(
                  child: SingleChildScrollView(
                    child: Text(
                      line?.transcript ?? 'Settle in.',
                      key: const Key('player_line'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall?.copyWith(
                        height: 1.4,
                        fontWeight: FontWeight.w400,
                      ),
                    ),
                  ),
                ),
              ),
              Row(
                children: <Widget>[
                  Expanded(
                    child: Semantics(
                      button: true,
                      label: playing
                          ? 'Pause the session'
                          : 'Resume the session',
                      child: OutlinedButton(
                        key: const Key('player_pause_resume'),
                        onPressed: playing ? _pause : _start,
                        child: Text(playing ? 'Pause' : 'Resume'),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Semantics(
                      button: true,
                      label: 'End the session now and go to feedback',
                      child: FilledButton(
                        key: const Key('player_end'),
                        onPressed: _end,
                        child: const Text('End session'),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
