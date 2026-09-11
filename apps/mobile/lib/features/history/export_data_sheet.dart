import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';

/// "Export my meditation data".
///
/// Fetches everything the service holds for this device and shows it, with a
/// copy action. No email address is asked for and nothing is uploaded anywhere:
/// an export that required handing over contact details would be a worse deal
/// than the one the privacy policy describes.
Future<void> showExportDataSheet(BuildContext context) async {
  final AppScope scope = AppScope.of(context);
  final NavigatorState navigator = Navigator.of(context);

  // Not awaited on purpose: the spinner stays up while the request runs and is
  // dismissed below. Awaiting it here would block until the user closed it.
  unawaited(
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (BuildContext context) => const Center(
        key: Key('export_loading'),
        child: CircularProgressIndicator(),
      ),
    ),
  );

  Map<String, dynamic>? payload;
  String? error;
  try {
    payload = await scope.api.exportMyData();
  } on ApiException catch (failure) {
    error = failure.statusCode == 404
        ? 'There is nothing stored for this device yet.'
        : failure.message;
  }

  navigator.pop(); // dismiss the spinner
  if (!context.mounted) {
    return;
  }

  if (payload == null) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(error ?? 'Export failed.')));
    return;
  }

  final String pretty = const JsonEncoder.withIndent('  ').convert(payload);
  final Map<String, int> counts = <String, int>{
    for (final MapEntry<String, dynamic> entry in payload.entries)
      if (entry.value is List) entry.key: (entry.value as List<dynamic>).length,
  };

  if (!context.mounted) {
    return;
  }
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (BuildContext context) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.75,
      builder: (BuildContext context, ScrollController controller) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          key: const Key('export_sheet'),
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(
              'Your meditation data',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              counts.entries
                  .map((MapEntry<String, int> e) => '${e.value} ${e.key}')
                  .join(' · ')
                  .replaceAll('_', ' '),
              key: const Key('export_summary'),
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 12),
            Expanded(
              child: SingleChildScrollView(
                controller: controller,
                child: SelectableText(
                  pretty,
                  key: const Key('export_payload'),
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                ),
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              key: const Key('export_copy'),
              icon: const Icon(Icons.copy_all_outlined),
              label: const Text('Copy as JSON'),
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: pretty));
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Copied to the clipboard.')),
                  );
                }
              },
            ),
          ],
        ),
      ),
    ),
  );
}
