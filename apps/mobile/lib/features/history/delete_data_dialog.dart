import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';

/// "Delete my meditation data".
///
/// One confirmation step that says exactly what will be removed, a destructive
/// action styled as destructive, and no retention checkbox, no pre-selected
/// "keep my data" option and no copy arguing the user out of it. Cancel is the
/// plain button; delete is the emphasised one, because the user opened this
/// dialog in order to delete.
Future<bool> showDeleteDataDialog(BuildContext context) async {
  final AppScope scope = AppScope.of(context);
  final bool? confirmed = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      key: const Key('delete_data_dialog'),
      title: const Text('Delete my meditation data'),
      content: const Text(
        'This permanently deletes your check-ins, sessions and feedback from '
        'the service. It cannot be undone, and nothing is kept behind.',
      ),
      actions: <Widget>[
        TextButton(
          key: const Key('delete_data_cancel'),
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('delete_data_confirm'),
          style: FilledButton.styleFrom(
            backgroundColor: Theme.of(context).colorScheme.error,
            foregroundColor: Theme.of(context).colorScheme.onError,
          ),
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Delete'),
        ),
      ],
    ),
  );

  if (confirmed != true) {
    return false;
  }

  try {
    await scope.api.deleteMyData();
    // Forget the local identifier too, so the next session starts as a new
    // guest rather than writing back to the id just erased.
    await scope.guest.reset();
    return true;
  } on ApiException catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.message)));
    }
    return false;
  }
}
