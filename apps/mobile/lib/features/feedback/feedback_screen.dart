import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
import '../../core/models.dart';
import '../history/history_store.dart';

/// Before/after feedback.
///
/// The wording asks how the user feels now. No clinical meaning is attached to
/// the numbers, and none is shown back to the user.
class FeedbackScreen extends StatefulWidget {
  const FeedbackScreen({
    required this.session,
    required this.beforeScore,
    required this.completed,
    super.key,
  });

  final MeditationSession session;
  final int beforeScore;
  final bool completed;

  @override
  State<FeedbackScreen> createState() => _FeedbackScreenState();
}

class _FeedbackScreenState extends State<FeedbackScreen> {
  int _afterScore = 5;
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
          afterScore: _afterScore,
          helpfulness: _helpfulness,
          completed: widget.completed,
          beforeScore: widget.beforeScore,
          notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
        ),
      );
      scope.history.add(
        SessionHistoryEntry(
          sessionId: widget.session.id,
          practiceName: widget.session.recommendation.practicePublicName,
          durationMinutes: widget.session.recommendation.durationMinutes,
          completed: widget.completed,
          recordedAt: DateTime.now(),
          afterScore: _afterScore,
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
            Text(
              'How does it feel now?',
              style: theme.textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              'Before you started you put stress at ${widget.beforeScore}.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            Semantics(
              label: 'Stress now, $_afterScore out of 10',
              child: Slider(
                key: const Key('feedback_after_score'),
                value: _afterScore.toDouble(),
                min: 0,
                max: 10,
                divisions: 10,
                label: '$_afterScore',
                onChanged: (double value) =>
                    setState(() => _afterScore = value.round()),
              ),
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
