import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import 'history_store.dart';

/// Recent sessions from this run of the app.
///
/// Deliberately labelled as such: Program001 keeps no durable local history and
/// the screen does not imply one.
class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final List<SessionHistoryEntry> entries = AppScope.of(context).history.entries;
    return Scaffold(
      appBar: AppBar(title: const Text('Recent sessions')),
      body: SafeArea(
        child: entries.isEmpty
            ? const Center(
                key: Key('history_empty'),
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: Text(
                    'No sessions yet. Your finished sessions from this run of '
                    'the app appear here.',
                    textAlign: TextAlign.center,
                  ),
                ),
              )
            : ListView.separated(
                itemCount: entries.length,
                separatorBuilder: (_, _) => const Divider(height: 1),
                itemBuilder: (BuildContext context, int index) {
                  final SessionHistoryEntry entry = entries[index];
                  return ListTile(
                    title: Text(entry.practiceName),
                    subtitle: Text(
                      '${entry.durationMinutes} min - '
                      '${entry.completed ? 'completed' : 'ended early'}',
                    ),
                    trailing: entry.afterScore == null
                        ? null
                        : Text('after ${entry.afterScore}'),
                  );
                },
              ),
      ),
    );
  }
}
