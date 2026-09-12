import '../../core/timeline.dart';

/// The run states, mirroring the backend exactly.
///
/// There is no `backgrounded` state. Backgrounding is an OS event, not
/// something a session is: a session playing in the user's pocket is playing.
enum RunState {
  created('created'),
  preparing('preparing'),
  ready('ready'),
  playing('playing'),
  paused('paused'),
  completed('completed'),
  abandoned('abandoned'),
  failed('failed');

  const RunState(this.wireValue);

  final String wireValue;

  bool get isTerminal => this == completed || this == abandoned;
}

enum RunCommand {
  prepare('prepare'),
  resolved('resolved'),
  unresolvable('unresolvable'),
  start('start'),
  pause('pause'),
  resume('resume'),
  interrupt('interrupt'),
  interruptionEnded('interruption_ended'),
  complete('complete'),
  abandon('abandon'),
  fail('fail'),
  recover('recover');

  const RunCommand(this.wireValue);

  final String wireValue;
}

/// The transition table, the same one the backend holds.
///
/// Duplicated rather than fetched because the client must know what is legal
/// while offline, and a table this small drifting is caught by a test that
/// compares it against the OpenAPI command enum.
const Map<RunState, Map<RunCommand, RunState>> _transitions =
    <RunState, Map<RunCommand, RunState>>{
      RunState.created: <RunCommand, RunState>{
        RunCommand.prepare: RunState.preparing,
        RunCommand.abandon: RunState.abandoned,
      },
      RunState.preparing: <RunCommand, RunState>{
        RunCommand.resolved: RunState.ready,
        RunCommand.unresolvable: RunState.failed,
        RunCommand.abandon: RunState.abandoned,
      },
      RunState.ready: <RunCommand, RunState>{
        RunCommand.start: RunState.playing,
        RunCommand.abandon: RunState.abandoned,
        RunCommand.fail: RunState.failed,
      },
      RunState.playing: <RunCommand, RunState>{
        RunCommand.pause: RunState.paused,
        RunCommand.interrupt: RunState.paused,
        RunCommand.complete: RunState.completed,
        RunCommand.abandon: RunState.abandoned,
        RunCommand.fail: RunState.failed,
      },
      RunState.paused: <RunCommand, RunState>{
        RunCommand.resume: RunState.playing,
        RunCommand.abandon: RunState.abandoned,
        RunCommand.fail: RunState.failed,
        RunCommand.interrupt: RunState.paused,
        // An interruption ending never resumes playback. The user decides when
        // a voice starts talking again.
        RunCommand.interruptionEnded: RunState.paused,
      },
      RunState.failed: <RunCommand, RunState>{
        RunCommand.recover: RunState.ready,
        RunCommand.abandon: RunState.abandoned,
      },
    };

/// One thing that happened, queued for the backend.
class PlaybackEvent {
  const PlaybackEvent({
    required this.sequence,
    required this.eventType,
    required this.elapsedMs,
    this.segmentId,
    this.commandId,
  });

  final int sequence;
  final String eventType;
  final int elapsedMs;
  final String? segmentId;
  final String? commandId;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'sequence': sequence,
    'event_type': eventType,
    'elapsed_ms': elapsedMs,
    if (segmentId != null) 'segment_id': segmentId,
    if (commandId != null) 'command_id': commandId,
  };
}

/// Whether a reconciliation was applied, and why it was refused if not.
enum ReconcileOutcome {
  applied,

  /// The snapshot was older than what this client already knows.
  staleSnapshot,

  /// The run has already ended; a snapshot cannot revive it.
  terminalRun,
}

/// The player, with no timer, no audio and no widget in it.
///
/// Everything is driven by [tickTo], which the caller supplies from a monotonic
/// source. That is what makes the whole player unit-testable and what keeps a
/// device whose wall clock jumps - a timezone change, an NTP correction - from
/// moving a meditation's position. Elapsed is playback time: a session paused
/// at minute three and resumed the next morning is still at minute three.
class PlaybackController {
  PlaybackController({
    required this.plan,
    required String Function() commandIdFactory,
    RunState initialState = RunState.created,
    int initialPositionMs = 0,
  }) : _commandId = commandIdFactory,
       _state = initialState,
       _positionMs = initialPositionMs;

  final SessionPlanV2 plan;
  final String Function() _commandId;

  RunState _state;
  int _positionMs;
  int _sequence = 0;
  int? _runningSinceMs;
  final List<PlaybackEvent> _pending = <PlaybackEvent>[];

  RunState get state => _state;
  int get positionMs => _positionMs;
  int get sequence => _sequence;
  bool get isPlaying => _state == RunState.playing;

  /// Events not yet accepted by the backend. Drained by [takePending].
  List<PlaybackEvent> get pending => List<PlaybackEvent>.unmodifiable(_pending);

  ScheduledSegment? get currentSegment => plan.segmentAt(_positionMs);

  double get progress => plan.progressAt(_positionMs);

  int get remainingMs => (plan.totalMs - _positionMs).clamp(0, plan.totalMs);

  /// What to show right now: the live line, or the last one spoken.
  ///
  /// During silence the previous speech stays on screen rather than being
  /// replaced by nothing, because a blank screen reads as the app having
  /// stopped working.
  TimelineSegment? get visibleSpeech {
    final ScheduledSegment? scheduled = currentSegment;
    if (scheduled == null) {
      return null;
    }
    for (int i = scheduled.index; i >= 0; i--) {
      if (plan.schedule[i].segment.isSpeech) {
        return plan.schedule[i].segment;
      }
    }
    return null;
  }

  bool get isInSilence => currentSegment?.segment.isSilence ?? false;

  bool can(RunCommand command) =>
      !_state.isTerminal &&
      (_transitions[_state]?.containsKey(command) ?? false);

  /// Apply a command locally. Returns the event to send, or null if it was not
  /// legal - an illegal command is dropped rather than thrown, because the UI
  /// asking twice is not worth crashing a meditation over.
  PlaybackEvent? apply(RunCommand command, {int? nowMs, String? segmentId}) {
    if (!can(command)) {
      return null;
    }
    final RunState next = _transitions[_state]![command]!;

    if (_state == RunState.playing &&
        next != RunState.playing &&
        nowMs != null) {
      _bank(nowMs);
    }
    if (next == RunState.playing &&
        _state != RunState.playing &&
        nowMs != null) {
      _runningSinceMs = nowMs;
    }

    _state = next;
    _sequence += 1;
    final PlaybackEvent event = PlaybackEvent(
      sequence: _sequence,
      eventType: _eventFor(command),
      elapsedMs: _positionMs,
      segmentId: segmentId ?? currentSegment?.segment.id,
      commandId: _commandId(),
    );
    _pending.add(event);
    return event;
  }

  /// Advance to a monotonic reading. Ignored while not playing.
  void tickTo(int nowMs) {
    if (_state != RunState.playing || _runningSinceMs == null) {
      return;
    }
    if (nowMs < _runningSinceMs!) {
      // Monotonic time cannot go backwards; a reading that says otherwise is
      // a bad reading, not a reason to rewind the session.
      return;
    }
    _positionMs += nowMs - _runningSinceMs!;
    _runningSinceMs = nowMs;
  }

  /// True once the timeline has been played through.
  bool get reachedEnd => _positionMs >= plan.totalMs;

  /// Move to where playback should restart after an interruption.
  void seekToResumePoint() {
    _positionMs = plan.resumePosition(_positionMs);
  }

  /// Adopt a server snapshot, refusing anything that would go backwards.
  ReconcileOutcome reconcile({
    required RunState state,
    required int positionMs,
    required int sequence,
  }) {
    if (_state.isTerminal && !state.isTerminal) {
      // A finished run stays finished. A late snapshot describing it as
      // playing is describing a moment that has passed.
      return ReconcileOutcome.terminalRun;
    }
    if (sequence < _sequence) {
      return ReconcileOutcome.staleSnapshot;
    }

    _state = state;
    // Position only ever moves forward: a snapshot taken before the last
    // local tick is not evidence that time went backwards.
    _positionMs = positionMs > _positionMs ? positionMs : _positionMs;
    _sequence = sequence;
    // Never leave a playing controller without a clock anchor. A resumed run
    // establishes a new anchor when the user resumes, never here.
    _runningSinceMs = null;
    if (_state == RunState.playing) {
      _state = RunState.paused;
    }
    return ReconcileOutcome.applied;
  }

  /// Take the queued events for sending. They are removed only on success.
  List<PlaybackEvent> takePending() => List<PlaybackEvent>.from(_pending);

  void acknowledge(List<PlaybackEvent> sent) {
    final Set<int> sequences = sent
        .map((PlaybackEvent e) => e.sequence)
        .toSet();
    _pending.removeWhere((PlaybackEvent e) => sequences.contains(e.sequence));
  }

  /// Record something that is not a state change, such as a route change.
  PlaybackEvent note(String eventType) {
    _sequence += 1;
    final PlaybackEvent event = PlaybackEvent(
      sequence: _sequence,
      eventType: eventType,
      elapsedMs: _positionMs,
      segmentId: currentSegment?.segment.id,
    );
    _pending.add(event);
    return event;
  }

  void _bank(int nowMs) {
    tickTo(nowMs);
    _runningSinceMs = null;
  }

  static String _eventFor(RunCommand command) {
    switch (command) {
      case RunCommand.prepare:
        return 'session_created';
      case RunCommand.resolved:
      case RunCommand.recover:
        return 'session_prepared';
      case RunCommand.unresolvable:
        return 'render_failure';
      case RunCommand.start:
        return 'session_started';
      case RunCommand.pause:
        return 'playback_paused';
      case RunCommand.resume:
        return 'playback_resumed';
      case RunCommand.interrupt:
        return 'playback_interrupted';
      case RunCommand.interruptionEnded:
        return 'playback_focus_regained';
      case RunCommand.complete:
        return 'session_completed';
      case RunCommand.abandon:
        return 'session_abandoned';
      case RunCommand.fail:
        return 'playback_failed';
    }
  }
}

/// mm:ss for a non-negative number of milliseconds.
String formatDuration(int milliseconds) {
  final int seconds = (milliseconds < 0 ? 0 : milliseconds) ~/ 1000;
  final String minutes = (seconds ~/ 60).toString().padLeft(2, '0');
  final String remainder = (seconds % 60).toString().padLeft(2, '0');
  return '$minutes:$remainder';
}
