import 'package:flutter/material.dart';

import '../../core/models.dart';

/// The whole session as text.
///
/// Three different people need this and it costs one screen: someone who is
/// deaf, someone whose device TTS is broken, and someone who simply wants to
/// read ahead. It is also the last rung of the fallback chain, which is why it
/// is a first-class surface rather than a debug view.
class TranscriptSheet extends StatelessWidget {
  const TranscriptSheet({
    required this.plan,
    super.key,
    this.currentSegmentId,
    this.personalization,
  });

  final SessionPlanV2 plan;
  final String? currentSegmentId;

  /// Program005 provenance, when the session carries it.
  final Personalization? personalization;

  static Future<void> show(
    BuildContext context, {
    required SessionPlanV2 plan,
    String? currentSegmentId,
    Personalization? personalization,
  }) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext context) => TranscriptSheet(
      plan: plan,
      currentSegmentId: currentSegmentId,
      personalization: personalization,
    ),
  );

  /// What was personalized, which policy did it and whether AI was used —
  /// the transcript is where someone checking the words looks for this.
  static String describe(Personalization p) {
    final String variant = p.presentationVariant == 'returning'
        ? 'Returning opening'
        : 'Standard opening';
    final String ai = p.usedAi
        ? 'AI wording (${p.providerId})'
        : 'no AI wording';
    return '$variant · ${p.reasonText.toLowerCase()} · '
        'policy ${p.policyVersion} · $ai';
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final List<TimelineSegment> lines = plan.speech;

    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.8,
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Semantics(
                header: true,
                child: Text(
                  'Session transcript',
                  key: const Key('transcript_title'),
                  style: theme.textTheme.titleLarge,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Everything this session says, in order.',
                style: theme.textTheme.bodySmall,
              ),
              if (personalization != null) ...<Widget>[
                const SizedBox(height: 4),
                Text(
                  describe(personalization!),
                  key: const Key('transcript_personalization'),
                  style: theme.textTheme.bodySmall,
                ),
              ],
              const SizedBox(height: 16),
              Flexible(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: lines.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 16),
                  itemBuilder: (BuildContext context, int index) {
                    final TimelineSegment line = lines[index];
                    final bool isCurrent = line.id == currentSegmentId;
                    return Semantics(
                      selected: isCurrent,
                      child: Text(
                        line.transcript,
                        key: Key('transcript_line_$index'),
                        style: theme.textTheme.bodyLarge?.copyWith(
                          height: 1.4,
                          fontWeight: isCurrent
                              ? FontWeight.w600
                              : FontWeight.w400,
                        ),
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
