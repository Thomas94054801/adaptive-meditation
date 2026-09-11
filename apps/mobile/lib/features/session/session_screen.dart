import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/models.dart';
import '../feedback/feedback_screen.dart';
import 'session_timeline.dart';

/// The session player.
///
/// The clock only advances an elapsed-seconds counter; everything shown is
/// derived from [SessionTimeline], which is pure. Program001 renders stage text
/// rather than speech: audio arrives through TtsProvider without the session
/// domain changing.
class SessionScreen extends StatefulWidget {
  const SessionScreen({
    required this.session,
    required this.beforeState,
    super.key,
    this.autoStart = true,
  });

  final MeditationSession session;

  /// The check-in this session came from, kept so the feedback screen can ask
  /// for the same four scales and the backend can compute a real before/after.
  final CheckIn beforeState;

  /// Disabled in widget tests so no timer outlives the test.
  final bool autoStart;

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  late final SessionTimeline _timeline = SessionTimeline(widget.session.plan);
  Timer? _ticker;
  int _elapsedSeconds = 0;
  bool _running = false;

  @override
  void initState() {
    super.initState();
    if (widget.autoStart) {
      _resume();
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  void _resume() {
    _ticker?.cancel();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    setState(() => _running = true);
  }

  void _pause() {
    _ticker?.cancel();
    _ticker = null;
    setState(() => _running = false);
  }

  void _tick() {
    setState(() => _elapsedSeconds++);
    if (_elapsedSeconds >= _timeline.totalSeconds) {
      _pause();
      _finish(completed: true);
    }
  }

  Future<void> _finish({required bool completed}) async {
    _ticker?.cancel();
    _ticker = null;
    if (!mounted) {
      return;
    }
    // How much of the planned session actually ran. Measured, not assumed:
    // "completed" is the user's intent and this is what happened.
    final int total = _timeline.totalSeconds;
    final double ratio = total <= 0
        ? 1
        : (_elapsedSeconds / total).clamp(0.0, 1.0);
    await Navigator.of(context).pushReplacement<void, void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => FeedbackScreen(
          session: widget.session,
          beforeState: widget.beforeState,
          completed: completed,
          completionRatio: ratio,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final TimelineFrame frame = _timeline.frameAt(_elapsedSeconds);

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.session.plan.publicTitle),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              LinearProgressIndicator(
                key: const Key('session_progress'),
                value: _timeline.progressAt(_elapsedSeconds),
                minHeight: 6,
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: <Widget>[
                  Text(
                    'Stage ${frame.stageIndex + 1} of '
                    '${widget.session.plan.stages.length}',
                    style: theme.textTheme.labelLarge,
                  ),
                  Text(
                    formatClock(frame.secondsRemaining),
                    key: const Key('session_remaining'),
                    style: theme.textTheme.labelLarge,
                  ),
                ],
              ),
              const SizedBox(height: 32),
              Expanded(
                child: Center(
                  child: SingleChildScrollView(
                    child: Text(
                      frame.isSilence ? 'Stay with it.' : frame.stage.prompt,
                      key: const Key('session_prompt'),
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
                    child: OutlinedButton(
                      key: const Key('session_pause_resume'),
                      onPressed: _running ? _pause : _resume,
                      child: Text(_running ? 'Pause' : 'Resume'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      key: const Key('session_end'),
                      onPressed: () => _finish(completed: false),
                      child: const Text('End session'),
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
