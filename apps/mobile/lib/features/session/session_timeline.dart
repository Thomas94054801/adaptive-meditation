import '../../core/models.dart';

/// What the player should show at one instant of a session.
class TimelineFrame {
  const TimelineFrame({
    required this.stageIndex,
    required this.stage,
    required this.elapsedSeconds,
    required this.secondsIntoStage,
    required this.secondsRemaining,
    required this.isSilence,
    required this.isComplete,
  });

  final int stageIndex;
  final SessionStage stage;
  final int elapsedSeconds;
  final int secondsIntoStage;
  final int secondsRemaining;

  /// True during the silent tail of a stage, when no new guidance is given.
  final bool isSilence;
  final bool isComplete;
}

/// Pure session player logic.
///
/// Deterministic by construction: the frame is a function of the plan and the
/// elapsed seconds only. No timer, no clock and no widget is involved, so the
/// whole player is unit-testable and behaves identically on every device.
class SessionTimeline {
  const SessionTimeline(this.plan);

  final SessionPlan plan;

  int get totalSeconds => plan.totalSeconds;

  /// Progress in 0..1, clamped at both ends.
  double progressAt(int elapsedSeconds) {
    if (totalSeconds <= 0) {
      return 1;
    }
    final double ratio = elapsedSeconds / totalSeconds;
    return ratio.clamp(0.0, 1.0);
  }

  /// The frame for [elapsedSeconds]. Values past the end return the last stage
  /// marked complete rather than throwing.
  TimelineFrame frameAt(int elapsedSeconds) {
    final int elapsed = elapsedSeconds < 0 ? 0 : elapsedSeconds;
    final bool complete = elapsed >= totalSeconds;
    final int index = complete
        ? plan.stages.length - 1
        : _stageIndexAt(elapsed);
    final SessionStage stage = plan.stages[index];
    final int into = complete
        ? stage.durationSeconds
        : elapsed - stage.startOffsetSeconds;
    final int guidedSeconds = stage.durationSeconds - stage.silenceAfterSeconds;

    return TimelineFrame(
      stageIndex: index,
      stage: stage,
      elapsedSeconds: elapsed > totalSeconds ? totalSeconds : elapsed,
      secondsIntoStage: into,
      secondsRemaining: complete ? 0 : totalSeconds - elapsed,
      isSilence: !complete && into >= guidedSeconds,
      isComplete: complete,
    );
  }

  int _stageIndexAt(int elapsed) {
    for (int i = 0; i < plan.stages.length; i++) {
      if (elapsed < plan.stages[i].endOffsetSeconds) {
        return i;
      }
    }
    return plan.stages.length - 1;
  }
}

/// mm:ss for a non-negative number of seconds.
String formatClock(int seconds) {
  final int safe = seconds < 0 ? 0 : seconds;
  final String minutes = (safe ~/ 60).toString().padLeft(2, '0');
  final String remainder = (safe % 60).toString().padLeft(2, '0');
  return '$minutes:$remainder';
}
