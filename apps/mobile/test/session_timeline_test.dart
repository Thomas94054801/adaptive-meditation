import 'package:adaptive_meditation/features/session/session_timeline.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

void main() {
  final SessionTimeline timeline = const SessionTimeline(FakeMeditationApi.plan);

  test('total length matches the plan', () {
    expect(timeline.totalSeconds, 600);
  });

  test('stage boundaries resolve to the right stage', () {
    expect(timeline.frameAt(0).stage.id, 'arrive');
    expect(timeline.frameAt(59).stage.id, 'arrive');
    expect(timeline.frameAt(60).stage.id, 'sweep');
    expect(timeline.frameAt(539).stage.id, 'sweep');
    expect(timeline.frameAt(540).stage.id, 'close');
    expect(timeline.frameAt(599).stage.id, 'close');
  });

  test('progress is clamped at both ends', () {
    expect(timeline.progressAt(-10), 0.0);
    expect(timeline.progressAt(0), 0.0);
    expect(timeline.progressAt(300), 0.5);
    expect(timeline.progressAt(600), 1.0);
    expect(timeline.progressAt(900), 1.0);
  });

  test('remaining seconds count down to zero and stop', () {
    expect(timeline.frameAt(0).secondsRemaining, 600);
    expect(timeline.frameAt(120).secondsRemaining, 480);
    expect(timeline.frameAt(600).secondsRemaining, 0);
    expect(timeline.frameAt(1200).secondsRemaining, 0);
  });

  test('the silent tail of a stage is reported', () {
    // arrive runs 60s with a 10s silent tail, so silence starts at t=50.
    expect(timeline.frameAt(49).isSilence, isFalse);
    expect(timeline.frameAt(50).isSilence, isTrue);
    expect(timeline.frameAt(59).isSilence, isTrue);
    expect(timeline.frameAt(60).isSilence, isFalse);
  });

  test('completion is reported once past the end, without throwing', () {
    expect(timeline.frameAt(599).isComplete, isFalse);
    expect(timeline.frameAt(600).isComplete, isTrue);
    expect(timeline.frameAt(5000).isComplete, isTrue);
    expect(timeline.frameAt(5000).stage.id, 'close');
  });

  test('negative elapsed time is treated as the start', () {
    expect(timeline.frameAt(-5).elapsedSeconds, 0);
    expect(timeline.frameAt(-5).stage.id, 'arrive');
  });

  test('every second of the session resolves to exactly one stage', () {
    for (int second = 0; second < timeline.totalSeconds; second++) {
      final TimelineFrame frame = timeline.frameAt(second);
      expect(
        second >= frame.stage.startOffsetSeconds &&
            second < frame.stage.endOffsetSeconds,
        isTrue,
        reason: 'second $second fell outside stage ${frame.stage.id}',
      );
    }
  });

  test('the player is deterministic: the same second gives the same frame', () {
    for (int second = 0; second <= 600; second += 37) {
      final TimelineFrame a = timeline.frameAt(second);
      final TimelineFrame b = timeline.frameAt(second);
      expect(a.stage.id, b.stage.id);
      expect(a.secondsRemaining, b.secondsRemaining);
      expect(a.isSilence, b.isSilence);
    }
  });

  test('clock formatting pads and floors at zero', () {
    expect(formatClock(0), '00:00');
    expect(formatClock(9), '00:09');
    expect(formatClock(70), '01:10');
    expect(formatClock(600), '10:00');
    expect(formatClock(-5), '00:00');
  });
}
