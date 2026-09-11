/// One finished or abandoned session, as the local list shows it.
class SessionHistoryEntry {
  const SessionHistoryEntry({
    required this.sessionId,
    required this.practiceName,
    required this.durationMinutes,
    required this.completed,
    required this.recordedAt,
    this.afterScore,
  });

  final String sessionId;
  final String practiceName;
  final int durationMinutes;
  final bool completed;
  final DateTime recordedAt;
  final int? afterScore;
}

/// In-memory session list for Program001.
///
/// Deliberately not persistent: the app shows recent sessions from this run and
/// says so, rather than implying a durable history it does not yet keep. The
/// list is capped so it cannot grow without bound during a long session of use;
/// at the cap the oldest entry is dropped.
class SessionHistoryStore {
  SessionHistoryStore({this.maxEntries = 50});

  final int maxEntries;
  final List<SessionHistoryEntry> _entries = <SessionHistoryEntry>[];

  List<SessionHistoryEntry> get entries =>
      List<SessionHistoryEntry>.unmodifiable(_entries.reversed);

  void add(SessionHistoryEntry entry) {
    _entries.add(entry);
    while (_entries.length > maxEntries) {
      _entries.removeAt(0);
    }
  }
}
