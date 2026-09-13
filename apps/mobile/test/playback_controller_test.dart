import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/session/playback_controller.dart';
import 'package:adaptive_meditation/platform/audio_session.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

/// Program004 Slice E - the client player, without a widget or a clock.
void main() {
  final SessionPlanV2 plan = FakeMeditationApi.typedPlan;

  PlaybackController controller({
    RunState state = RunState.created,
    int positionMs = 0,
  }) {
    int counter = 0;
    return PlaybackController(
      plan: plan,
      commandIdFactory: () => 'command-${++counter}',
      initialState: state,
      initialPositionMs: positionMs,
    );
  }

  PlaybackController playing() {
    final PlaybackController c = controller();
    c.apply(RunCommand.prepare, nowMs: 0);
    c.apply(RunCommand.resolved, nowMs: 0);
    c.apply(RunCommand.start, nowMs: 0);
    return c;
  }

  group('state machine', () {
    test('mirrors the backend: playing requires being prepared first', () {
      final PlaybackController c = controller();
      expect(c.can(RunCommand.start), isFalse);
      expect(c.apply(RunCommand.start), isNull);
      expect(c.state, RunState.created);
    });

    test('an interruption ending never resumes playback', () {
      final PlaybackController c = playing();
      c.apply(RunCommand.interrupt, nowMs: 1000);
      expect(c.state, RunState.paused);
      c.apply(RunCommand.interruptionEnded, nowMs: 2000);
      expect(c.state, RunState.paused);
    });

    test('terminal states accept nothing', () {
      final PlaybackController c = playing();
      c.apply(RunCommand.complete, nowMs: 1000);
      expect(c.state, RunState.completed);
      expect(c.state.isTerminal, isTrue);
      for (final RunCommand command in RunCommand.values) {
        expect(c.can(command), isFalse, reason: command.name);
      }
    });

    test('failure is recoverable rather than terminal', () {
      final PlaybackController c = playing();
      c.apply(RunCommand.fail, nowMs: 500);
      expect(c.state, RunState.failed);
      expect(c.state.isTerminal, isFalse);
      c.apply(RunCommand.recover, nowMs: 600);
      expect(c.state, RunState.ready);
    });

    test('there is no backgrounded state', () {
      expect(
        RunState.values.map((RunState s) => s.wireValue),
        isNot(contains('backgrounded')),
      );
    });
  });

  group('playback time', () {
    test('a paused controller does not advance', () {
      final PlaybackController c = playing();
      c.tickTo(10000);
      expect(c.positionMs, 10000);

      c.apply(RunCommand.pause, nowMs: 10000);
      // Twelve hours later.
      c.tickTo(10000 + 12 * 60 * 60 * 1000);
      expect(c.positionMs, 10000);
    });

    test('position excludes every paused interval', () {
      final PlaybackController c = playing();
      c.tickTo(10000);
      c.apply(RunCommand.pause, nowMs: 10000);
      c.apply(RunCommand.resume, nowMs: 60000);
      c.tickTo(75000);
      expect(c.positionMs, 25000);
    });

    test('a monotonic reading going backwards does not rewind the session', () {
      final PlaybackController c = playing();
      c.tickTo(30000);
      c.tickTo(29000);
      expect(c.positionMs, 30000);
    });
  });

  group('segments', () {
    test('the schedule matches the backend, half-open', () {
      expect(plan.segmentAt(0)!.segment.id, 'bell_open');
      expect(plan.segmentAt(1999)!.segment.id, 'bell_open');
      expect(plan.segmentAt(2000)!.segment.id, 'speech_0_arrive');
      expect(plan.segmentAt(plan.totalMs), isNull);
    });

    test('resume rewinds inside speech and stands still inside silence', () {
      expect(plan.resumePosition(2000 + 4000), 2000);
      expect(plan.resumePosition(10000 + 1000), 11000);
    });

    test('the last spoken line stays on screen through the silence', () {
      final PlaybackController c = playing();
      c.tickTo(2000 + 8000 + 5000);
      expect(c.isInSilence, isTrue);
      expect(c.visibleSpeech!.id, 'speech_0_arrive');
    });

    test('progress and remaining agree with each other', () {
      final PlaybackController c = playing();
      expect(c.progress, 0);
      expect(c.remainingMs, plan.totalMs);
      c.tickTo(plan.totalMs);
      expect(c.progress, 1);
      expect(c.remainingMs, 0);
      expect(c.reachedEnd, isTrue);
    });
  });

  group('journal', () {
    test('every command queues one event with a command id and sequence', () {
      final PlaybackController c = playing();
      expect(c.pending.length, 3);
      expect(c.pending.map((PlaybackEvent e) => e.sequence), <int>[1, 2, 3]);
      expect(c.pending.map((PlaybackEvent e) => e.eventType), <String>[
        'session_created',
        'session_prepared',
        'session_started',
      ]);
      expect(c.pending.every((PlaybackEvent e) => e.commandId != null), isTrue);
    });

    test('command ids are unique, so a retry is distinguishable', () {
      final PlaybackController c = playing();
      final Set<String?> ids = c.pending
          .map((PlaybackEvent e) => e.commandId)
          .toSet();
      expect(ids.length, c.pending.length);
    });

    test('acknowledged events leave the queue and others stay', () {
      final PlaybackController c = playing();
      final List<PlaybackEvent> sent = c.takePending();
      c.note('route_changed');
      c.acknowledge(sent);
      expect(c.pending.length, 1);
      expect(c.pending.single.eventType, 'route_changed');
    });

    test('an illegal command queues nothing', () {
      final PlaybackController c = controller();
      c.apply(RunCommand.start);
      expect(c.pending, isEmpty);
    });
  });

  group('recovery', () {
    test('the backend view wins after a reconnect', () {
      final PlaybackController c = playing();
      c.tickTo(50000);
      c.adopt(state: RunState.paused, positionMs: 120000, sequence: 9);
      expect(c.state, RunState.paused);
      expect(c.positionMs, 120000);
      expect(c.sequence, 9);
      // Not running, so a later tick must not credit the gap.
      c.tickTo(999999);
      expect(c.positionMs, 120000);
    });

    test('seeking to the resume point never lands mid-utterance', () {
      final PlaybackController c = controller(
        state: RunState.paused,
        positionMs: 2000 + 4000,
      );
      c.seekToResumePoint();
      expect(c.positionMs, 2000);
    });
  });

  group('route policy', () {
    test('losing headphones to the speaker interrupts', () {
      expect(
        interruptionForRouteChange(AudioRoute.headphones, AudioRoute.speaker),
        AudioInterruption.wentPublic,
      );
    });

    test('plugging headphones in does not interrupt', () {
      expect(
        interruptionForRouteChange(AudioRoute.speaker, AudioRoute.headphones),
        isNull,
      );
    });

    test('swapping one private route for another does not interrupt', () {
      expect(
        interruptionForRouteChange(AudioRoute.headphones, AudioRoute.bluetooth),
        isNull,
      );
    });

    test('an unknown route counts as audible to the room', () {
      expect(AudioRoute.unknown.isPrivate, isFalse);
      expect(
        interruptionForRouteChange(AudioRoute.bluetooth, AudioRoute.unknown),
        AudioInterruption.wentPublic,
      );
    });
  });

  test('formatDuration renders mm:ss and clamps negatives', () {
    expect(formatDuration(0), '00:00');
    expect(formatDuration(65000), '01:05');
    expect(formatDuration(604000), '10:04');
    expect(formatDuration(-1), '00:00');
  });
}
