import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
import '../../core/models.dart';
import '../recommendation/recommendation_screen.dart';

/// Current-state check-in.
///
/// Accessible controls only: dropdowns, sliders and segmented buttons. Nothing
/// here asks for camera, microphone, location or health access.
class CheckInScreen extends StatefulWidget {
  const CheckInScreen({super.key});

  @override
  State<CheckInScreen> createState() => _CheckInScreenState();
}

class _CheckInScreenState extends State<CheckInScreen> {
  CheckIn _checkIn = const CheckIn(
    goal: Goal.stress,
    stress: 5,
    energy: 5,
    mentalActivity: 5,
    sleepiness: 5,
    availableMinutes: 10,
    experienceLevel: ExperienceLevel.beginner,
  );
  bool _busy = false;
  String? _error;

  Future<void> _continue() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final AppScope scope = AppScope.of(context);
    try {
      final CheckInReceipt receipt = await scope.api.submitCheckIn(_checkIn);
      final Recommendation recommendation = await scope.api.recommend(_checkIn);
      if (!mounted) {
        return;
      }
      await Navigator.of(context).push<void>(
        MaterialPageRoute<void>(
          builder: (BuildContext context) => RecommendationScreen(
            receipt: receipt,
            recommendation: recommendation,
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
    return Scaffold(
      appBar: AppBar(title: const Text('How are you right now?')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          children: <Widget>[
            _GoalField(
              value: _checkIn.goal,
              onChanged: (Goal goal) =>
                  setState(() => _checkIn = _checkIn.copyWith(goal: goal)),
            ),
            const SizedBox(height: 8),
            _ScaleField(
              label: 'Stress',
              helper: 'calm to very stressed',
              value: _checkIn.stress,
              onChanged: (int value) =>
                  setState(() => _checkIn = _checkIn.copyWith(stress: value)),
            ),
            _ScaleField(
              label: 'Energy',
              helper: 'depleted to energised',
              value: _checkIn.energy,
              onChanged: (int value) =>
                  setState(() => _checkIn = _checkIn.copyWith(energy: value)),
            ),
            _ScaleField(
              label: 'Mental activity',
              helper: 'quiet to racing',
              value: _checkIn.mentalActivity,
              onChanged: (int value) => setState(
                () => _checkIn = _checkIn.copyWith(mentalActivity: value),
              ),
            ),
            _ScaleField(
              label: 'Sleepiness',
              helper: 'wide awake to very sleepy',
              value: _checkIn.sleepiness,
              onChanged: (int value) => setState(
                () => _checkIn = _checkIn.copyWith(sleepiness: value),
              ),
            ),
            const SizedBox(height: 8),
            _MinutesField(
              value: _checkIn.availableMinutes,
              onChanged: (int minutes) => setState(
                () => _checkIn = _checkIn.copyWith(availableMinutes: minutes),
              ),
            ),
            const SizedBox(height: 20),
            _ExperienceField(
              value: _checkIn.experienceLevel,
              onChanged: (ExperienceLevel level) => setState(
                () => _checkIn = _checkIn.copyWith(experienceLevel: level),
              ),
            ),
            const SizedBox(height: 28),
            if (_error != null) ...<Widget>[
              Text(
                _error!,
                key: const Key('check_in_error'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              const SizedBox(height: 12),
            ],
            FilledButton(
              key: const Key('check_in_submit'),
              onPressed: _busy ? null : _continue,
              child: _busy
                  ? const SizedBox(
                      height: 22,
                      width: 22,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('See my practice'),
            ),
          ],
        ),
      ),
    );
  }
}

class _GoalField extends StatelessWidget {
  const _GoalField({required this.value, required this.onChanged});

  final Goal value;
  final ValueChanged<Goal> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: DropdownButtonFormField<Goal>(
        key: const Key('check_in_goal'),
        initialValue: value,
        decoration: const InputDecoration(
          labelText: 'What would help most?',
          border: OutlineInputBorder(),
        ),
        items: <DropdownMenuItem<Goal>>[
          for (final Goal goal in Goal.values)
            DropdownMenuItem<Goal>(value: goal, child: Text(goal.label)),
        ],
        onChanged: (Goal? goal) {
          if (goal != null) {
            onChanged(goal);
          }
        },
      ),
    );
  }
}

class _ScaleField extends StatelessWidget {
  const _ScaleField({
    required this.label,
    required this.helper,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final String helper;
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Text(label, style: theme.textTheme.titleMedium),
              Text('$value', style: theme.textTheme.titleMedium),
            ],
          ),
          Text(
            helper,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          Semantics(
            label: '$label, $value out of 10',
            child: Slider(
              key: Key('scale_${label.toLowerCase().replaceAll(' ', '_')}'),
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

class _MinutesField extends StatelessWidget {
  const _MinutesField({required this.value, required this.onChanged});

  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Time available', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: <Widget>[
            for (final int minutes in availableMinutesOptions)
              ChoiceChip(
                key: Key('minutes_$minutes'),
                label: Text('$minutes min'),
                selected: value == minutes,
                onSelected: (bool selected) {
                  if (selected) {
                    onChanged(minutes);
                  }
                },
              ),
          ],
        ),
      ],
    );
  }
}

class _ExperienceField extends StatelessWidget {
  const _ExperienceField({required this.value, required this.onChanged});

  final ExperienceLevel value;
  final ValueChanged<ExperienceLevel> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Experience', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        SegmentedButton<ExperienceLevel>(
          key: const Key('check_in_experience'),
          segments: <ButtonSegment<ExperienceLevel>>[
            for (final ExperienceLevel level in ExperienceLevel.values)
              ButtonSegment<ExperienceLevel>(
                value: level,
                label: Text(level.label),
              ),
          ],
          selected: <ExperienceLevel>{value},
          onSelectionChanged: (Set<ExperienceLevel> selection) =>
              onChanged(selection.first),
        ),
      ],
    );
  }
}
