import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
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

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final AppScope scope = AppScope.of(context);
    final NavigatorState navigator = Navigator.of(context);
    try {
      await scope.api.submitFeedback(
        widget.session.id,
        SessionFeedback(
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
        ),
      );
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
      navigator.popUntil((Route<void> route) => route.isFirst);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.message);
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
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
