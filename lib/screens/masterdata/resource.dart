/// One row as the API returns it.
typedef JsonRow = Map<String, dynamic>;

enum FieldKind { text, decimal, toggle }

/// One editable field of a master-data resource. [key] is the JSON key the API uses.
class FieldSpec {
  const FieldSpec(
    this.key,
    this.label, {
    this.kind = FieldKind.text,
    this.mandatory = false,
    this.capitals = false,
    this.min,
    this.max,
    this.pattern,
    this.patternHint,
    this.unit,
  });

  final String key;
  final String label;
  final FieldKind kind;
  final bool mandatory;

  /// Typed in capitals (GSTIN, vehicle number).
  final bool capitals;

  /// Allowed range for a number. Catches a slipped decimal or the wrong unit.
  final num? min;
  final num? max;

  /// A text value must match this once spaces and hyphens are removed and it is upper-cased.
  final String? pattern;

  /// Shown when [pattern] does not match.
  final String? patternHint;

  /// Shown at the right edge of the field.
  final String? unit;

  /// The problem with a non-empty value, or null when it is fine.
  String? check(String value) {
    if (kind == FieldKind.decimal) {
      final n = double.tryParse(value);
      if (n == null) return 'Enter a number';
      if (min != null && n < min!) return 'Must be at least ${formatNumber(min!)}${unit == null ? '' : ' $unit'}';
      if (max != null && n > max!) return 'Must be at most ${formatNumber(max!)}${unit == null ? '' : ' $unit'}';
    } else if (pattern != null) {
      final compact = value.replaceAll(RegExp(r'[\s-]'), '').toUpperCase();
      if (!RegExp(pattern!).hasMatch(compact)) return patternHint;
    }
    return null;
  }
}

/// Everything the generic list and form screens need to know about one resource.
class Resource {
  const Resource({
    required this.path,
    required this.singular,
    required this.plural,
    required this.titleKey,
    required this.subtitle,
    required this.fields,
  });

  final String path;
  final String singular;
  final String plural;
  final String titleKey;
  final String Function(JsonRow row) subtitle;
  final List<FieldSpec> fields;
}

/// 60.0 -> "60", 61.5 -> "61.5".
String formatNumber(num value) => value == value.roundToDouble() ? value.toInt().toString() : value.toString();

String _size(JsonRow row, String prefix) =>
    '${formatNumber(row['${prefix}length_cm'] as num)} × ${formatNumber(row['${prefix}width_cm'] as num)} × '
    '${formatNumber(row['${prefix}height_cm'] as num)} cm';

const _gstinPattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$';

final parties = Resource(
  path: '/parties',
  singular: 'party',
  plural: 'Parties',
  titleKey: 'name',
  subtitle: (row) => [row['address'], row['gstin'], row['phone']].whereType<String>().join(' · '),
  fields: const [
    FieldSpec('name', 'Name', mandatory: true),
    FieldSpec('address', 'Address'),
    FieldSpec(
      'gstin',
      'GSTIN',
      capitals: true,
      pattern: _gstinPattern,
      patternHint: 'A GST number has 15 characters, like 24AABCR4141H1ZQ',
    ),
    FieldSpec('phone', 'Phone', pattern: r'^\+?[0-9]{10,13}$', patternHint: 'Enter 10 to 13 digits'),
    FieldSpec('latitude', 'Latitude', kind: FieldKind.decimal, min: -90, max: 90),
    FieldSpec('longitude', 'Longitude', kind: FieldKind.decimal, min: -180, max: 180),
  ],
);

final itemTypes = Resource(
  path: '/item-types',
  singular: 'item type',
  plural: 'Item types',
  titleKey: 'name',
  subtitle: (row) => '${_size(row, '')} · ${formatNumber(row['unit_weight_kg'] as num)} kg',
  fields: const [
    FieldSpec('name', 'Name', mandatory: true),
    FieldSpec('length_cm', 'Length', kind: FieldKind.decimal, mandatory: true, min: 1, max: 1500, unit: 'cm'),
    FieldSpec('width_cm', 'Width', kind: FieldKind.decimal, mandatory: true, min: 1, max: 1500, unit: 'cm'),
    FieldSpec('height_cm', 'Height', kind: FieldKind.decimal, mandatory: true, min: 1, max: 1500, unit: 'cm'),
    FieldSpec(
      'unit_weight_kg',
      'Weight of one unit',
      kind: FieldKind.decimal,
      mandatory: true,
      min: 0.01,
      max: 5000,
      unit: 'kg',
    ),
    FieldSpec('stackable', 'Can be stacked', kind: FieldKind.toggle),
  ],
);

final trucks = Resource(
  path: '/trucks',
  singular: 'truck',
  plural: 'Trucks',
  titleKey: 'vehicle_number',
  subtitle: (row) => [
    row['label'],
    _size(row, 'inner_'),
    '${formatNumber(row['payload_kg'] as num)} kg',
  ].whereType<String>().join(' · '),
  fields: const [
    FieldSpec(
      'vehicle_number',
      'Vehicle number',
      mandatory: true,
      capitals: true,
      pattern: r'^([A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$',
      patternHint: 'Enter a registration number like GJ03CW0620',
    ),
    FieldSpec('label', 'Label'),
    FieldSpec(
      'inner_length_cm',
      'Inner length',
      kind: FieldKind.decimal,
      mandatory: true,
      min: 100,
      max: 2000,
      unit: 'cm',
    ),
    FieldSpec('inner_width_cm', 'Inner width', kind: FieldKind.decimal, mandatory: true, min: 100, max: 300, unit: 'cm'),
    FieldSpec(
      'inner_height_cm',
      'Inner height',
      kind: FieldKind.decimal,
      mandatory: true,
      min: 100,
      max: 450,
      unit: 'cm',
    ),
    FieldSpec('payload_kg', 'Payload', kind: FieldKind.decimal, mandatory: true, min: 100, max: 60000, unit: 'kg'),
  ],
);
