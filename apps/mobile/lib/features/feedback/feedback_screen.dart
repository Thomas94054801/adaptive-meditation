import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
import '../../core/durable_store.dart';
import '../../core/models.dart';
import '../history/history_store.dart';

/// Before/after feedback.
///
/// The same four scales as the check-in, so the backend can compute the outcome
/// measure that matches the goal rather than inferring one from a single
/// number. No clinical meaning is attached to the values, and nothing derived
/// from them is shown back to the user.
class FeedbackScreen extends StatefulWidget {
  const FeedbackScreen({
    required this.session,
    required this.beforeState,
    required this.completed,
    required this.completionRatio,
    super.key,
  });

  final MeditationSession session;
  final CheckIn beforeState;
  final bool completed;
  final double completionRatio;

  @override
  State<FeedbackScreen> createState() => _FeedbackScreenState();
}

class _FeedbackScreenState extends State<FeedbackScreen> {
  late int _stress = widget.beforeState.stress;
  late int _energy = widget.beforeState.energy;
  late int _mentalActivity = widget.beforeState.mentalActivity;
  late int _sleepiness = widget.beforeState.sleepiness;
  int _helpfulness = 3;
  final TextEditingController _notes = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  /// Save durably, then tell the server once.
  ///
  /// The order is the whole point. Program004R could lose a session's feedback
  /// to a dropped connection, because the only copy lived in the request. Now
  /// a local commit is what lets the user leave, and the network is a
  /// best-effort follow-up: an unreachable backend leaves the row `pending` and
  /// does not trap anyone on this screen.
  ///
  /// A failed *local* write is different, and is reported as a failure: the
  /// screen stays, because there is nothing anywhere that remembers what was
  /// typed.
  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final AppScope scope = AppScope.of(context);
    final NavigatorState navigator = Navigator.of(context);
    final SessionFeedback feedback = SessionFeedback(
      afterScore: _stress,
      helpfulness: _helpfulness,
      completed: widget.completed,
      beforeScore: widget.beforeState.stress,
      notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
      stressAfter: _stress,
      energyAfter: _energy,
      mentalActivityAfter: _mentalActivity,
      sleepinessAfter: _sleepiness,
      completionRatio: widget.completionRatio,
    );

    final DurableStore? store = scope.store;
    if (store != null) {
      try {
        await store.saveFeedback(
          sessionId: widget.session.id,
          payload: feedback.toJson(),
          nowMs: DateTime.now().millisecondsSinceEpoch,
        );
      } on Object catch (error) {
        // Nothing was saved, so nothing may be claimed. Stay put.
        if (mounted) {
          setState(() {
            _error = 'Could not save your feedback on this device: $error';
            _busy = false;
          });
        }
        return;
      }
    }

    // Durably saved. From here the user may leave whatever the network does.
    scope.history.add(
      SessionHistoryEntry(
        sessionId: widget.session.id,
        practiceName: widget.session.recommendation.practicePublicName,
        durationMinutes: widget.session.recommendation.durationMinutes,
        completed: widget.completed,
        recordedAt: DateTime.now(),
        afterScore: _stress,
      ),
    );

    // The existing foreground request, attempted once. No retry scheduler, no
    // connectivity listener, no background worker - a later program may consume
    // the pending rows.
    try {
      await scope.api.submitFeedback(widget.session.id, feedback);
      await store?.markFeedbackSynced(
        widget.session.id,
        nowMs: DateTime.now().millisecondsSinceEpoch,
      );
    } on ApiException {
      // Left pending on purpose. The server upserts by session id, so writing
      // the same thing again later is harmless.
    } on Object {
      // Marking synced failed after the server accepted it. Also safe, for the
      // same reason, and not worth distributed-transaction machinery.
    }

    if (!mounted) {
      return;
    }
    setState(() => _busy = false);
    navigator.popUntil((Route<void> route) => route.isFirst);
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.completed ? 'Session complete' : 'Session ended'),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
          children: <Widget>[
            Text('How are you now?', style: theme.textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(
              'The same four questions as before, so you can see what shifted.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            _AfterScale(
              label: 'Stress',
              fieldKey: 'feedback_after_score',
              before: widget.beforeState.stress,
              value: _stress,
              onChanged: (int value) => setState(() => _stress = value),
            ),
            _AfterScale(
              label: 'Energy',
              fieldKey: 'feedback_energy_after',
              before: widget.beforeState.energy,
              value: _energy,
              onChanged: (int value) => setState(() => _energy = value),
            ),
            _AfterScale(
              label: 'Mental activity',
              fieldKey: 'feedback_mental_activity_after',
              before: widget.beforeState.mentalActivity,
              value: _mentalActivity,
              onChanged: (int value) => setState(() => _mentalActivity = value),
            ),
            _AfterScale(
              label: 'Sleepiness',
              fieldKey: 'feedback_sleepiness_after',
              before: widget.beforeState.sleepiness,
              value: _sleepiness,
              onChanged: (int value) => setState(() => _sleepiness = value),
            ),
            const SizedBox(height: 16),
            Text('Was this session useful?', style: theme.textTheme.titleLarge),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: <Widget>[
                for (int score = 1; score <= 5; score++)
                  ChoiceChip(
                    key: Key('feedback_helpfulness_$score'),
                    label: Text('$score'),
                    selected: _helpfulness == score,
                    onSelected: (bool selected) {
                      if (selected) {
                        setState(() => _helpfulness = score);
                      }
                    },
                  ),
              ],
            ),
            const SizedBox(height: 24),
            TextField(
              key: const Key('feedback_notes'),
              controller: _notes,
              maxLength: 1000,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Anything you want to note (optional)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            if (_error != null) ...<Widget>[
              Text(
                _error!,
                key: const Key('feedback_error'),
                style: TextStyle(color: theme.colorScheme.error),
              ),
              const SizedBox(height: 12),
            ],
            FilledButton(
              key: const Key('feedback_submit'),
              onPressed: _busy ? null : _submit,
              child: _busy
                  ? const SizedBox(
                      height: 22,
                      width: 22,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Done'),
            ),
          ],
        ),
      ),
    );
  }
}

class _AfterScale extends StatelessWidget {
  const _AfterScale({
    required this.label,
    required this.fieldKey,
    required this.before,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final String fieldKey;
  final int before;
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Text(label, style: theme.textTheme.titleMedium),
              Text(
                'was $before, now $value',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
          Semantics(
            label: '$label now, $value out of 10',
            child: Slider(
              key: Key(fieldKey),
              value: value.toDouble(),
              min: 0,
              max: 10,
              divisions: 10,
              label: '$value',
              onChanged: (double next) => onChanged(next.round()),
            ),
          ),
        ],
      ),
    );
  }
}
