String _two(int n) => n.toString().padLeft(2, '0');

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// An API timestamp as local "16 Nov 2026 · 14:54".
String dateTimeLabel(String iso) {
  final t = DateTime.parse(iso).toLocal();
  return '${t.day} ${_months[t.month - 1]} ${t.year} · ${_two(t.hour)}:${_two(t.minute)}';
}

/// "2026-11-15" -> "15 Nov 2026".
String dayLabel(String isoDate) {
  final d = DateTime.parse(isoDate);
  return '${d.day} ${_months[d.month - 1]} ${d.year}';
}

/// A range as people say it: "Nov 1–16", "Oct 28 – Nov 3", "Dec 2025 – Jan 2026" across years.
String rangeLabel(DateTime start, DateTime end) {
  final a = '${_months[start.month - 1]} ${start.day}';
  if (start.year != end.year) return '$a ${start.year} – ${_months[end.month - 1]} ${end.day} ${end.year}';
  if (start.month == end.month) return start.day == end.day ? a : '$a–${end.day}';
  return '$a – ${_months[end.month - 1]} ${end.day}';
}

/// "waiting 1 day", "waiting 3 days", "arrived today".
String waitingLabel(int days) => days == 0 ? 'arrived today' : 'waiting $days day${days == 1 ? '' : 's'}';

/// 1234567.5 -> "12,34,567.50": Indian digit grouping, always two decimals.
String rupees(num amount) {
  final fixed = amount.abs().toStringAsFixed(2);
  final whole = fixed.split('.')[0];
  final paise = fixed.split('.')[1];
  final last3 = whole.length > 3 ? whole.substring(whole.length - 3) : whole;
  var rest = whole.length > 3 ? whole.substring(0, whole.length - 3) : '';
  final groups = <String>[];
  while (rest.length > 2) {
    groups.insert(0, rest.substring(rest.length - 2));
    rest = rest.substring(0, rest.length - 2);
  }
  if (rest.isNotEmpty) groups.insert(0, rest);
  return '${amount < 0 ? '-' : ''}₹${[...groups, last3].join(',')}.$paise';
}

/// 1005.0 -> "1,005 kg", 12.5 -> "12.5 kg".
String kgLabel(num kg) {
  final whole = kg == kg.roundToDouble();
  final text = whole ? kg.toInt().toString() : kg.toStringAsFixed(1);
  final withCommas = whole && text.length > 3
      ? text.replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')
      : text;
  return '$withCommas kg';
}

/// An API amount ("1000.00") as "₹1,000.00".
String money(String amount) => rupees(double.parse(amount));
