/// Input rules shared by every form. They mirror the server's (backend/app/validators.py), so a
/// mistake is shown at once, before anything is sent; the server checks again regardless.
library;

/// A validator: the problem with a non-empty, trimmed value, or null when it is fine.
typedef Rule = String? Function(String value);

final _letter = RegExp(r'\p{L}', unicode: true);
final _spaces = RegExp(r'\s+');

/// Trimmed, with runs of spaces made single.
String tidy(String value) => value.trim().replaceAll(_spaces, ' ');

bool _hasLetter(String value) => _letter.hasMatch(value);

/// Company, party, branch, truck owner and item-type names: at least 2 characters, with letters.
String? businessName(String value) {
  final v = tidy(value);
  if (v.length < 2 || !_hasLetter(v)) return 'Must be at least 2 characters and cannot contain only numbers or symbols.';
  if (!RegExp(r"^[\p{L}\p{N}\s&.,'()/@#+\-_]+$", unicode: true).hasMatch(v)) {
    return "Use letters, numbers, spaces and . , & ' - / ( ) # only.";
  }
  return null;
}

/// A person's full name: letters, spaces, hyphens, apostrophes and dots for initials.
String? personName(String value) {
  final v = tidy(value);
  if (v.length < 2) return 'Enter the full name.';
  if (!RegExp(r"^\p{L}+(?:[ .'\-]+\p{L}+)*\.?$", unicode: true).hasMatch(v)) {
    return 'Use letters, spaces, hyphens and apostrophes only.';
  }
  return null;
}

/// An address, when given, must contain letters.
String? address(String value) =>
    _hasLetter(value) ? null : 'An address must contain letters, not only numbers or symbols.';

/// A city or town: letters (and spaces, dots, hyphens), 2 to 30 characters.
String? city(String value) {
  final v = tidy(value);
  if (!RegExp(r"^\p{L}[\p{L} .'\-]*$", unicode: true).hasMatch(v)) return 'Enter a city name using letters only, like RAJKOT.';
  if (v.length < 2 || v.length > 30) return 'A city name is 2 to 30 letters.';
  return null;
}

/// Comma-separated city names: each valid, none empty, none twice.
String? cityList(String value) {
  final parts = value.split(',').map((p) => tidy(p).toUpperCase()).toList();
  if (parts.any((p) => p.isEmpty)) return 'Remove the empty entry between commas.';
  for (final p in parts) {
    final problem = city(p);
    if (problem != null) return '$p: $problem';
  }
  if (parts.toSet().length != parts.length) return 'A city is listed twice.';
  return null;
}

/// Indian mobile numbers: 10 digits starting with 6, 7, 8 or 9 (after any +91 or 0).
String? indianMobile(String value) {
  var digits = value.replaceAll(RegExp(r'[\s()\-.]'), '');
  if (digits.startsWith('+91')) digits = digits.substring(3);
  if (digits.length == 12 && digits.startsWith('91')) digits = digits.substring(2);
  if (digits.length == 11 && digits.startsWith('0')) digits = digits.substring(1);
  return RegExp(r'^[6-9][0-9]{9}$').hasMatch(digits) ? null : 'Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.';
}

String? pan(String value) => RegExp(r'^[A-Z]{5}[0-9]{4}[A-Z]$').hasMatch(value.replaceAll(' ', '').toUpperCase())
    ? null
    : 'Enter a valid 10-character PAN, like ABCDE1234F.';

const _gstChars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';

/// GSTIN: format, state code and the mod-36 check character.
String? gstin(String value) {
  final v = value.replaceAll(' ', '').toUpperCase();
  if (!RegExp(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$').hasMatch(v)) {
    return 'Enter a valid 15-character GSTIN, like 24AABCR4141H1ZQ.';
  }
  final state = int.parse(v.substring(0, 2));
  if (!((state >= 1 && state <= 38) || state == 97 || state == 99)) return "The GSTIN's first two digits are not an Indian state code.";
  var total = 0;
  for (var i = 0; i < 14; i++) {
    final product = _gstChars.indexOf(v[i]) * (i.isOdd ? 2 : 1);
    total += product ~/ 36 + product % 36;
  }
  final check = _gstChars[(36 - total % 36) % 36];
  return check == v[14] ? null : "This GSTIN's last character does not match; check it for a typing mistake.";
}

Rule digits(String name, List<int> lengths) => (value) {
      final v = value.replaceAll(' ', '');
      return RegExp(r'^[0-9]+$').hasMatch(v) && lengths.contains(v.length)
          ? null
          : 'Enter a valid $name: ${lengths.join(' or ')} digits.';
    };

final hsnCode = digits('HSN code', [4, 6, 8]);
final ewayBillNumber = digits('e-way bill number', [12]);

String? enrolmentId(String value) =>
    RegExp(r'^[0-9A-Z]{15}$').hasMatch(value.replaceAll(' ', '').toUpperCase()) ? null : 'Enter the 15-character enrolment ID from ENR-03.';

/// A number above zero, at most [max], with at most [places] decimals. ".5" is read as 0.5.
Rule positive({num? max, int places = 2, String? unit}) => (value) {
      final n = number(value);
      if (n == null) return 'Enter a number';
      if (n <= 0) return 'Must be more than 0';
      if (max != null && n > max) return 'Must be at most $max${unit == null ? '' : ' $unit'}';
      final decimals = value.contains('.') ? value.split('.').last.length : 0;
      if (decimals > places) return 'Use at most $places decimal places';
      return null;
    };

/// Parses a typed number, accepting ".5" and "5." and rejecting "-0000"-style signs only by value.
double? number(String value) {
  var v = value.trim();
  if (v.startsWith('.')) v = '0$v';
  if (v.startsWith('-.')) v = '-0${v.substring(1)}';
  if (!RegExp(r'^-?[0-9]+(\.[0-9]*)?$').hasMatch(v)) return null;
  return double.tryParse(v);
}

/// The number as the server should receive it: ".5" -> "0.5", "007" -> "7".
String normalizeNumber(String value) {
  final n = number(value);
  if (n == null) return value.trim();
  return n == n.roundToDouble() && !value.contains('.') ? n.toInt().toString() : n.toString();
}

const minPassword = 12;

/// Password strength by length and guessability, not character classes. Passphrases are welcome.
/// The server also refuses the 100,000 most common passwords.
String? newPassword(String value) {
  if (value.length < minPassword) return 'Use at least $minPassword characters. A short phrase of a few words is easy to remember.';
  if (value.length > 128) return 'Use at most 128 characters.';
  if (value.trim().isEmpty) return 'The password cannot be only spaces.';
  final compact = value.replaceAll(' ', '');
  if (RegExp(r'^[0-9]+$').hasMatch(compact)) return "Don't use only numbers; add some words.";
  if (RegExp(r'^[a-zA-Z]+$').hasMatch(compact) && compact.toLowerCase().split('').toSet().length < 6) {
    return 'Too easy to guess. Use a few different words.';
  }
  if (value.split('').toSet().length <= 3) return 'Too easy to guess: it repeats the same few characters.';
  return null;
}
