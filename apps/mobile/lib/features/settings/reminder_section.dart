import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/durable_store.dart';
import '../../core/preferences.dart';
import '../../core/reminders.dart';
import '../../platform/providers.dart';

/// The daily-reminder group of the settings screen — Program005 Slice C.
///
/// The switch reflects what the person asked for; the line under it reflects
/// what is actually true (scheduled, or why not). Turning it on opens an
/// explanation sheet, and only that sheet's Continue asks the OS.
class ReminderSection extends StatefulWidget {
  const ReminderSection({super.key});

  @override
  State<ReminderSection> createState() => _ReminderSectionState();
}

class _ReminderSectionState extends State<ReminderSection> {
  ReminderController? _controller;
  ReminderStatus? _status;
  bool _busy = false;

  static const ReminderTime _defaultTime = ReminderTime(hour: 8, minute: 0);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_controller == null) {
      final AppScope scope = AppScope.of(context);
      final DurableStore? store = scope.store;
      if (store != null) {
        _controller = ReminderController(
          notifications: scope.adapters.notifications,
          preferences: Preferences(store),
        );
        _refresh();
      }
    }
  }

  Future<void> _refresh() async {
    final ReminderStatus status = await _controller!.status();
    if (mounted) {
      setState(() => _status = status);
    }
  }

  ReminderTime get _time {
    final ReminderPreference? intent = _status?.intent;
    return intent != null && intent.hasTime
        ? ReminderTime(hour: intent.hour!, minute: intent.minute!)
        : _defaultTime;
  }

  Future<void> _run(Future<ReminderStatus> Function() action) async {
    setState(() => _busy = true);
    try {
      final ReminderStatus status = await action();
      if (mounted) {
        setState(() => _status = status);
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _toggle(bool on) async {
    if (!on) {
      await _run(_controller!.disable);
      return;
    }
    // The explanation first. Nothing has asked the OS yet.
    final bool? proceed = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (BuildContext context) => const _OptInSheet(),
    );
    if (proceed != true) {
      return;
    }
    await _run(() => _controller!.optIn(_time));
  }

  Future<void> _pickTime() async {
    final ReminderTime current = _time;
    final DurableStore store = AppScope.of(context).store!;
    final TimeOfDay? picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: current.hour, minute: current.minute),
    );
    if (picked == null) {
      return;
    }
    final ReminderTime time = ReminderTime(
      hour: picked.hour,
      minute: picked.minute,
    );
    if (_status?.intent.enabled ?? false) {
      await _run(() => _controller!.changeTime(time));
    } else {
      // Not on yet: remember the time, ask nothing.
      await Preferences(store).setReminder(
        ReminderPreference(
          enabled: false,
          hour: time.hour,
          minute: time.minute,
        ),
      );
      await _refresh();
    }
  }

  String _describe(ReminderStatus status) {
    if (status.active) {
      return 'Scheduled daily at ${status.scheduled!.time} '
          '(${status.scheduled!.zoneId}).';
    }
    return switch (status.problem) {
      ReminderProblem.permissionDenied =>
        'Not scheduled: notifications are off for this app. '
            'You can allow them in system settings.',
      ReminderProblem.zoneUnknown =>
        'Not scheduled: this device\'s time zone could not be read.',
      ReminderProblem.scheduleFailed =>
        'Not scheduled: the reminder could not be set. Tap to retry.',
      ReminderProblem.deletionPending =>
        'Paused while your data is being deleted.',
      null => 'Off.',
    };
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ReminderStatus? status = _status;
    if (_controller == null) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
          child: Text('Reminder', style: theme.textTheme.titleSmall),
        ),
        SwitchListTile(
          key: const Key('settings_reminder'),
          title: const Text('Daily reminder'),
          subtitle: Text(
            status == null ? 'Loading…' : _describe(status),
            key: const Key('settings_reminder_state'),
          ),
          value: status?.intent.enabled ?? false,
          onChanged: status == null || _busy ? null : _toggle,
        ),
        ListTile(
          key: const Key('settings_reminder_time'),
          title: const Text('Time'),
          trailing: Text(_time.toString(), style: theme.textTheme.titleMedium),
          enabled: status != null && !_busy,
          onTap: _pickTime,
        ),
        if (status?.problem == ReminderProblem.scheduleFailed)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextButton(
              key: const Key('settings_reminder_retry'),
              onPressed: _busy ? null : () => _run(_controller!.reconcile),
              child: const Text('Retry'),
            ),
          ),
      ],
    );
  }
}

/// What the person is agreeing to, before the OS asks. Local, this device,
/// off whenever they like. "Not now" asks nothing.
class _OptInSheet extends StatelessWidget {
  const _OptInSheet();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(
              'A daily reminder',
              key: const Key('reminder_optin_title'),
              style: theme.textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              'A local reminder at the time you choose. It stays on this '
              'device, says nothing about you, and you can turn it off any '
              'time. Your phone will ask whether to allow notifications.',
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('reminder_optin_continue'),
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Continue'),
            ),
            TextButton(
              key: const Key('reminder_optin_not_now'),
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Not now'),
            ),
          ],
        ),
      ),
    );
  }
}
