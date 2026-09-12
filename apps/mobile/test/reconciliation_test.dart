import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/session/playback_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

/// R09 and the G6 investigation, client side.
///
/// G6 was a hypothesis read out of the code, not a reproduced failure: that
/// unawaited command delivery plus unconditional sequence adoption could push
/// the client's sequence backwards, after which every later command reused a
/// number the server had already seen and was dropped as a replay.
///
/// It is recorded here as CONFIRMED BY INSPECTION and NOT REPRODUCED as a
/// failing test - see the note in the G6 group for why, and what is tested
/// instead. The remaining tests assert the invariants that make the failure
/// impossible.
void main() {
  final SessionPlanV2 plan = FakeMeditationApi.typedPlan;

  PlaybackController playing() {
    int counter = 0;
    final PlaybackController c = PlaybackController(
      plan: plan,
      commandIdFactory: () => 'command-${++counter}',
    );
    c.apply(RunCommand.prepare, nowMs: 0);
    c.apply(RunCommand.resolved, nowMs: 0);
    c.apply(RunCommand.start, nowMs: 0);
    return c;
  }

  group('G6', () {
    // Disposition: the hypothesis is CONFIRMED BY INSPECTION of the pre-fix
    // code, and NOT reproduced as a failing test against it.
    //
    // Why not: reproducing it needs the old `adopt`, which assigned any
    // incoming sequence unconditionally (see this file's history at
    // d1d0674 - player_screen.dart called adopt with
    // `sequence: state.commandSequence` and no comparison). Keeping that
    // method alive only to fail a test would mean shipping the defect as
    // production code. Simulating it with local variables would be a test
    // that asserts nothing about this program.
    //
    // So what is tested is the guard itself, driven through the exact
    // interleaving the hypothesis describes: command 3 applied locally, then a
    // late reply to command 1 arrives. Under the old rule the sequence became
    // 1 and every later command reused a number the server had already seen.
    // Under this rule the snapshot is refused.

    test('the G6 interleaving is refused rather than applied', () {
      final PlaybackController c = playing();
      c.tickTo(5000);
      expect(c.sequence, 3, reason: 'three commands applied locally');

      // The late reply to command 1, arriving after command 3.
      final ReconcileOutcome outcome = c.reconcile(
        state: RunState.playing,
        positionMs: 1000,
        sequence: 1,
      );

      expect(outcome, ReconcileOutcome.staleSnapshot);
      expect(c.sequence, 3, reason: 'the sequence must not go backwards');
      expect(c.positionMs, 5000, reason: 'nor may position');

      // And the run still accepts commands, which is what the old rule broke:
      // a wedged run looked alive while every command was dropped as a replay.
      final PlaybackEvent? next = c.apply(RunCommand.pause, nowMs: 6000);
      expect(next, isNotNull);
      expect(next!.sequence, 4, reason: 'numbering continues past the server');
    });

    test('a newer snapshot is applied', () {
      final PlaybackController c = playing();
      final ReconcileOutcome outcome = c.reconcile(
        state: RunState.paused,
        positionMs: 120000,
        sequence: 9,
      );
      expect(outcome, ReconcileOutcome.applied);
      expect(c.sequence, 9);
      expect(c.positionMs, 120000);
      expect(c.state, RunState.paused);
    });
  });

  group('reconciliation invariants', () {
    test('position never moves backwards', () {
      final PlaybackController c = playing();
      c.tickTo(60000);
      c.reconcile(state: RunState.paused, positionMs: 1000, sequence: 5);
      expect(c.positionMs, 60000);
    });

    test('a terminal run is not revived', () {
      final PlaybackController c = playing();
      c.apply(RunCommand.complete, nowMs: 1000);
      expect(c.state, RunState.completed);

      final ReconcileOutcome outcome = c.reconcile(
        state: RunState.playing,
        positionMs: 5000,
        sequence: 99,
      );
      expect(outcome, ReconcileOutcome.terminalRun);
      expect(c.state, RunState.completed);
    });

    test('a snapshot never leaves the controller playing without a clock', () {
      final PlaybackController c = playing();
      c.reconcile(state: RunState.playing, positionMs: 30000, sequence: 8);

      // Presented as paused and resumable. A relaunch or a reconnect must not
      // start making sound on its own; the user resumes, and that is when a
      // new monotonic anchor is established.
      expect(c.state, RunState.paused);
      expect(c.isPlaying, isFalse);

      // And no accidental time credit from a stale anchor.
      c.tickTo(999999);
      expect(c.positionMs, 30000);
    });

    test('un-ACKed events survive reconciliation', () {
      final PlaybackController c = playing();
      expect(c.pending, hasLength(3));
      c.reconcile(state: RunState.paused, positionMs: 9000, sequence: 7);
      expect(
        c.pending,
        hasLength(3),
        reason: 'a snapshot must not swallow operations the server never saw',
      );
    });

    test('acknowledging removes only what was confirmed', () {
      final PlaybackController c = playing();
      final List<PlaybackEvent> sent = <PlaybackEvent>[c.pending.first];
      c.note('route_changed');
      c.acknowledge(sent);

      expect(
        c.pending.map((PlaybackEvent e) => e.eventType),
        isNot(contains('session_created')),
      );
      expect(
        c.pending.map((PlaybackEvent e) => e.eventType),
        contains('route_changed'),
      );
    });
  });

  group('command identity', () {
    test('a retry keeps its command id', () {
      // The server matches on command_id, so generating a new one on retry
      // turns one command into two.
      final PlaybackController c = playing();
      final PlaybackEvent first = c.pending.first;
      expect(first.commandId, isNotNull);

      // Re-sending is re-sending the stored event, not building a new one.
      final List<PlaybackEvent> retry = c.takePending();
      expect(retry.first.commandId, first.commandId);
      expect(retry.first.sequence, first.sequence);
    });

    test('command ids are unique per command', () {
      final PlaybackController c = playing();
      final Set<String?> ids = c.pending
          .map((PlaybackEvent e) => e.commandId)
          .toSet();
      expect(ids, hasLength(c.pending.length));
    });

    test('observational events carry no command id', () {
      // Commands and events must not share a deduplication namespace.
      final PlaybackController c = playing();
      final PlaybackEvent note = c.note('route_changed');
      expect(note.commandId, isNull);
      expect(note.sequence, greaterThan(3));
    });
  });
}
