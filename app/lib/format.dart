String _two(int n) => n.toString().padLeft(2, '0');

/// An API timestamp as local "04-10-2026 14:54".
String dateTimeLabel(String iso) {
  final t = DateTime.parse(iso).toLocal();
  return '${_two(t.day)}-${_two(t.month)}-${t.year} ${_two(t.hour)}:${_two(t.minute)}';
}

/// "waiting 1 day", "waiting 3 days", "arrived today".
String waitingLabel(int days) => days == 0 ? 'arrived today' : 'waiting $days day${days == 1 ? '' : 's'}';
