import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
import '../../core/models.dart';
import '../../core/reasons.dart';
import '../session/player_screen.dart';
import '../session/session_screen.dart';

/// Shows the selected practice, how long it runs, and why - in plain language.
///
/// Internal source mappings are never displayed; the API does not return them.
class RecommendationScreen extends StatefulWidget {
  const RecommendationScreen({
    required this.receipt,
    required this.recommendation,
    super.key,
  });

  final CheckInReceipt receipt;
  final Recommendation recommendation;

  @override
  State<RecommendationScreen> createState() => _RecommendationScreenState();
}

class _RecommendationScreenState extends State<RecommendationScreen> {
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Report exposure once the explanation is actually on screen. Assignment
    // happened server-side when the recommendation was requested; counting that
    // as exposure would inflate every denominator the experiment is for.
    WidgetsBinding.instance.addPostFrameCallback((_) => _reportExposure());
  }

  Future<void> _reportExposure() async {
    final ExperimentVariant? variant = widget.recommendation.explanationVariant;
    if (variant == null || !mounted) {
      return;
    }
    try {
      await AppScope.of(context).api.recordExposure(
        experimentId: variant.experimentId,
        // The check-in this explanation was shown for. Re-opening the screen
        // for the same check-in is the same exposure, not a new one.
        context: widget.receipt.id,
      );
    } on ApiException {
      // An unrecorded exposure is a gap in analytics, not a broken session.
      // It must never interrupt someone trying to meditate.
    }
  }

  Future<void> _start() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final AppScope scope = AppScope.of(context);
    try {
      final MeditationSession session = await scope.api.createSession(
        widget.receipt.id,
      );
      final SessionPlanV2? typedPlan = session.planV2;
      if (typedPlan == null) {
        // A session the backend could not give a typed plan. It still plays,
        // on the stage timeline, and the legacy start call is its only way of
        // recording that it began.
        await scope.api.startSession(session.id);
      }
      if (!mounted) {
        return;
      }
      await Navigator.of(context).push<void>(
        MaterialPageRoute<void>(
          builder: (BuildContext context) => typedPlan == null
              ? SessionScreen(
                  session: session,
                  beforeState: widget.receipt.checkIn,
                )
              // The player drives the run state machine itself, so it does not
              // need the legacy start call: one authority over the run.
              : PlayerScreen(
                  session: session,
                  plan: typedPlan,
                  beforeState: widget.receipt.checkIn,
                ),
        ),
      );
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
    final Recommendation recommendation = widget.recommendation;
    final String? explanation = explainRecommendationVariant(
      recommendation.practicePublicName,
      recommendation.reasonCodes,
      variant: recommendation.explanationVariant?.variant ?? 'concise',
    );

    return Scaffold(
      appBar: AppBar(title: const Text('Your practice')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(
                recommendation.practicePublicName,
                key: const Key('recommendation_title'),
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '${recommendation.durationMinutes} minutes',
                key: const Key('recommendation_duration'),
                style: theme.textTheme.titleMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 20),
              if (explanation != null)
                Text(
                  explanation,
                  key: const Key('recommendation_reason'),
                  style: theme.textTheme.bodyLarge,
                ),
              const Spacer(),
              if (_error != null) ...<Widget>[
                Text(
                  _error!,
                  key: const Key('recommendation_error'),
                  style: TextStyle(color: theme.colorScheme.error),
                ),
                const SizedBox(height: 12),
              ],
              FilledButton(
                key: const Key('recommendation_start'),
                onPressed: _busy ? null : _start,
                child: _busy
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Start'),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Change my check-in'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
