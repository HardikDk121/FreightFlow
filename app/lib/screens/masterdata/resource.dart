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
  });

  final String key;
  final String label;
  final FieldKind kind;
  final bool mandatory;

  /// Typed in capitals (GSTIN, vehicle number).
  final bool capitals;
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

final parties = Resource(
  path: '/parties',
  singular: 'party',
  plural: 'Parties',
  titleKey: 'name',
  subtitle: (row) => [row['address'], row['gstin'], row['phone']].whereType<String>().join(' · '),
  fields: const [
    FieldSpec('name', 'Name', mandatory: true),
    FieldSpec('address', 'Address'),
    FieldSpec('gstin', 'GSTIN', capitals: true),
    FieldSpec('phone', 'Phone'),
    FieldSpec('latitude', 'Latitude', kind: FieldKind.decimal),
    FieldSpec('longitude', 'Longitude', kind: FieldKind.decimal),
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
    FieldSpec('length_cm', 'Length (cm)', kind: FieldKind.decimal, mandatory: true),
    FieldSpec('width_cm', 'Width (cm)', kind: FieldKind.decimal, mandatory: true),
    FieldSpec('height_cm', 'Height (cm)', kind: FieldKind.decimal, mandatory: true),
    FieldSpec('unit_weight_kg', 'Weight of one unit (kg)', kind: FieldKind.decimal, mandatory: true),
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
    FieldSpec('vehicle_number', 'Vehicle number', mandatory: true, capitals: true),
    FieldSpec('label', 'Label'),
    FieldSpec('inner_length_cm', 'Inner length (cm)', kind: FieldKind.decimal, mandatory: true),
    FieldSpec('inner_width_cm', 'Inner width (cm)', kind: FieldKind.decimal, mandatory: true),
    FieldSpec('inner_height_cm', 'Inner height (cm)', kind: FieldKind.decimal, mandatory: true),
    FieldSpec('payload_kg', 'Payload (kg)', kind: FieldKind.decimal, mandatory: true),
  ],
);
