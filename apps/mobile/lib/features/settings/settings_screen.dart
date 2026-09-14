import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/durable_store.dart';
import '../../core/preferences.dart';

/// The one settings screen — Program005.
///
/// Nothing is asked that personalization does not use, and nothing here
/// prompts for an OS permission on its own: opening this screen is not
/// consent to anything.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool? _adaptiveWording;
  bool _saving = false;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_adaptiveWording == null) {
      _load();
    }
  }

  Future<void> _load() async {
    final DurableStore? store = AppScope.of(context).store;
    final bool value = store == null
        ? true
        : await Preferences(store).adaptiveWordingEnabled();
    if (mounted) {
      setState(() => _adaptiveWording = value);
    }
  }

  Future<void> _setAdaptiveWording(bool value) async {
    final DurableStore? store = AppScope.of(context).store;
    final bool previous = _adaptiveWording ?? true;
    setState(() {
      _adaptiveWording = value;
      _saving = true;
      _error = null;
    });
    try {
      if (store == null) {
        throw StateError('no durable store');
      }
      await Preferences(store).setAdaptiveWordingEnabled(value);
    } catch (_) {
      // The switch shows what is stored, not what was tapped. A write that
      // failed leaves the previous value in force, and says so.
      if (mounted) {
        setState(() {
          _adaptiveWording = previous;
          _error =
              'Could not save this setting. It is still ${previous ? 'on' : 'off'}.';
        });
      }
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool? adaptive = _adaptiveWording;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.symmetric(vertical: 8),
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text('Wording', style: theme.textTheme.titleSmall),
            ),
            SwitchListTile(
              key: const Key('settings_adaptive_wording'),
              title: const Text('Adapt the wording to my history'),
              subtitle: const Text(
                'When on, a practice you have completed before opens with a '
                'shorter introduction. The practice itself never changes.',
              ),
              value: adaptive ?? true,
              onChanged: adaptive == null || _saving
                  ? null
                  : _setAdaptiveWording,
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  _error!,
                  key: const Key('settings_error'),
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.error,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
