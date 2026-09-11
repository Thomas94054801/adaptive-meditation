import 'package:flutter/material.dart';

import '../../app/app_scope.dart';
import '../../core/api.dart';
import '../../core/models.dart';
import 'delete_data_dialog.dart';
import 'export_data_sheet.dart';

/// The guest's sessions, read from the backend.
///
/// Program001 kept this list in memory and lost it on restart; the screen said
/// so. It is now durable and scoped to this guest's own identifier, which is
/// also what makes the delete action below meaningful.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  final List<SessionHistoryItem> _items = <SessionHistoryItem>[];
  String? _cursor;
  bool _hasMore = true;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadMore());
  }

  Future<void> _loadMore() async {
    if (_loading || !_hasMore) {
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final SessionHistoryPage page = await AppScope.of(
        context,
      ).api.sessionHistory(cursor: _cursor);
      if (!mounted) {
        return;
      }
      setState(() {
        _items.addAll(page.items);
        _cursor = page.nextCursor;
        _hasMore = page.hasMore && page.nextCursor != null;
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.message);
      }
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _refresh() async {
    setState(() {
      _items.clear();
      _cursor = null;
      _hasMore = true;
    });
    await _loadMore();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your sessions'),
        actions: <Widget>[
          IconButton(
            key: const Key('history_export_data'),
            tooltip: 'Export my meditation data',
            icon: const Icon(Icons.ios_share),
            onPressed: () => showExportDataSheet(context),
          ),
          IconButton(
            key: const Key('history_delete_data'),
            tooltip: 'Delete my meditation data',
            icon: const Icon(Icons.delete_outline),
            onPressed: () async {
              final bool deleted = await showDeleteDataDialog(context);
              if (deleted && mounted) {
                await _refresh();
              }
            },
          ),
        ],
      ),
      body: SafeArea(child: _body()),
    );
  }

  Widget _body() {
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(_error!, key: const Key('history_error'), textAlign: TextAlign.center),
              const SizedBox(height: 16),
              OutlinedButton(onPressed: _refresh, child: const Text('Try again')),
            ],
          ),
        ),
      );
    }
    if (_items.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: _loading
              ? const CircularProgressIndicator()
              : const Text(
                  'No sessions yet. Once you finish one it will appear here.',
                  key: Key('history_empty'),
                  textAlign: TextAlign.center,
                ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.separated(
        itemCount: _items.length + (_hasMore ? 1 : 0),
        separatorBuilder: (_, _) => const Divider(height: 1),
        itemBuilder: (BuildContext context, int index) {
          if (index >= _items.length) {
            _loadMore();
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          final SessionHistoryItem item = _items[index];
          return ListTile(
            title: Text(item.publicTitle),
            subtitle: Text(
              '${item.durationMinutes} min - '
              '${item.completed ? 'completed' : 'ended early'}',
            ),
            trailing: Text(_shortDate(item.createdAt)),
          );
        },
      ),
    );
  }

  static String _shortDate(DateTime value) {
    final DateTime local = value.toLocal();
    return '${local.year}-${local.month.toString().padLeft(2, '0')}-'
        '${local.day.toString().padLeft(2, '0')}';
  }
}
