import 'package:flutter/material.dart';

import '../../validation.dart';

/// One row as the API returns it.
typedef JsonRow = Map<String, dynamic>;

enum FieldKind { text, decimal, toggle, date, list }

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
    this.row,
    this.hint,
    this.helper,
    this.rule,
    this.phone = false,
    this.integer = false,
  });

  /// A shared rule from validation.dart (business name, GSTIN, city...), the same as the server's.
  final Rule? rule;

  /// Shown with the country-code phone field.
  final bool phone;

  /// A decimal field that takes whole numbers only (model year).
  final bool integer;

  /// Fields next to each other with the same [row] share one line on the form.
  final String? row;

  /// Placeholder while empty, such as "e.g. GJ03CW0620".
  final String? hint;

  /// A line under the field, or under a switch's title.
  final String? helper;

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
      final n = number(value);
      if (n == null) return 'Enter a number';
      if (integer && n != n.roundToDouble()) return 'Enter a whole number';
      if (min != null && n < min!) return 'Must be at least ${formatNumber(min!)}${unit == null ? '' : ' $unit'}';
      if (max != null && n > max!) return 'Must be at most ${formatNumber(max!)}${unit == null ? '' : ' $unit'}';
    } else if (pattern != null) {
      final compact = value.replaceAll(RegExp(r'[\s-]'), '').toUpperCase();
      if (!RegExp(pattern!).hasMatch(compact)) return patternHint;
    }
    if (kind == FieldKind.list) {
      return rule == null ? null : cityList(value);
    }
    return rule?.call(value);
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
    required this.icon,
    required this.intro,
    this.customForm,
    this.crossCheck,
  });

  /// A rule across fields (latitude with longitude), given the typed values by key.
  final String? Function(Map<String, String> values)? crossCheck;

  /// Shown on the empty list and beside the form's heading.
  final IconData icon;

  /// One line under the add/edit form's title.
  final String intro;

  final String path;
  final String singular;
  final String plural;
  final String titleKey;
  final String Function(JsonRow row) subtitle;
  final List<FieldSpec> fields;

  /// A purpose-built add/edit screen, for a resource the generic form cannot express.
  /// It must pop with `true` after a save, like the generic form.
  final Widget Function(JsonRow? row)? customForm;
}

/// 60.0 -> "60", 61.5 -> "61.5".
String formatNumber(num value) => value == value.roundToDouble() ? value.toInt().toString() : value.toString();

String _size(JsonRow row, String prefix) =>
    '${formatNumber(row['${prefix}length_cm'] as num)} × ${formatNumber(row['${prefix}width_cm'] as num)} × '
    '${formatNumber(row['${prefix}height_cm'] as num)} cm';

final parties = Resource(
  icon: Icons.groups_outlined,
  intro: 'Save a customer, sender or consignee.',
  path: '/parties',
  singular: 'party',
  plural: 'Parties',
  titleKey: 'name',
  subtitle: (row) => [row['address'], row['gstin'], row['phone']].whereType<String>().join(' · '),
  crossCheck: (v) => (v['latitude']!.trim().isEmpty) != (v['longitude']!.trim().isEmpty)
      ? 'Give both latitude and longitude, or neither.'
      : null,
  fields: const [
    FieldSpec('name', 'Name', mandatory: true, rule: businessName),
    FieldSpec('address', 'Address', rule: address),
    FieldSpec('gstin', 'GSTIN', capitals: true, rule: gstin, helper: '15-character GST identification number'),
    FieldSpec('phone', 'Phone', phone: true),
    FieldSpec('latitude', 'Latitude', kind: FieldKind.decimal, min: -90, max: 90, row: 'location'),
    FieldSpec(
      'longitude',
      'Longitude',
      kind: FieldKind.decimal,
      min: -180,
      max: 180,
      row: 'location',
      helper: 'Coordinates help with route planning.',
    ),
  ],
);

final itemTypes = Resource(
  icon: Icons.inventory_2_outlined,
  intro: 'Standardise your packages for better loads. Sizes in centimetres.',
  path: '/item-types',
  singular: 'item type',
  plural: 'Item types',
  titleKey: 'name',
  subtitle: (row) => '${_size(row, '')} · ${formatNumber(row['unit_weight_kg'] as num)} kg',
  fields: const [
    FieldSpec('name', 'Name', mandatory: true, rule: businessName),
    FieldSpec('length_cm', 'Length', kind: FieldKind.decimal, mandatory: true, min: 1, max: 1500, unit: 'cm', row: 'size'),
    FieldSpec('width_cm', 'Width', kind: FieldKind.decimal, mandatory: true, min: 1, max: 1500, unit: 'cm', row: 'size'),
    FieldSpec('height_cm', 'Height', kind: FieldKind.decimal, mandatory: true, min: 1, max: 1500, unit: 'cm', row: 'size'),
    FieldSpec(
      'unit_weight_kg',
      'Weight of one unit',
      kind: FieldKind.decimal,
      mandatory: true,
      min: 0.01,
      max: 5000,
      unit: 'kg',
    ),
    FieldSpec('stackable', 'Can be stacked', kind: FieldKind.toggle, helper: 'Allow items above this package.'),
  ],
);

final trucks = Resource(
  icon: Icons.local_shipping_outlined,
  intro: 'Dimensions, capacity and compliance. Certificates are checked before dispatch.',
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
      hint: 'e.g. GJ03CW0620',
    ),
    FieldSpec('label', 'Label', hint: 'e.g. Long haul'),
    FieldSpec('inner_length_cm', 'Inner L', kind: FieldKind.decimal, mandatory: true, min: 100, max: 2000, unit: 'cm', row: 'inner'),
    FieldSpec('inner_width_cm', 'Inner W', kind: FieldKind.decimal, mandatory: true, min: 100, max: 300, unit: 'cm', row: 'inner'),
    FieldSpec('inner_height_cm', 'Inner H', kind: FieldKind.decimal, mandatory: true, min: 100, max: 450, unit: 'cm', row: 'inner'),
    FieldSpec('payload_kg', 'Payload', kind: FieldKind.decimal, mandatory: true, min: 100, max: 60000, unit: 'kg', row: 'capacity'),
    FieldSpec('model_year', 'Model year', kind: FieldKind.decimal, mandatory: true, min: 1990, max: 2100, integer: true, row: 'capacity'),
    FieldSpec('insurance_expiry', 'Insurance expiry', kind: FieldKind.date, mandatory: true, row: 'papers'),
    FieldSpec('fitness_expiry', 'Fitness expiry', kind: FieldKind.date, mandatory: true, row: 'papers'),
    FieldSpec('current_station', 'Standing at', capitals: true),
  ],
);

final stations = Resource(
  icon: Icons.place_outlined,
  intro: 'A delivery station, the base station whose rates it uses, and its extra per kg.',
  path: '/stations',
  singular: 'station',
  plural: 'Stations',
  titleKey: 'name',
  subtitle: (row) {
    final extra = row['surcharge_per_kg'] as num;
    return '${row['zone']} rates${extra > 0 ? ' + Rs ${formatNumber(extra)} per kg' : ''}';
  },
  fields: const [
    FieldSpec('name', 'Station', mandatory: true, capitals: true),
    FieldSpec('zone', 'Uses the rates of (base station)', mandatory: true, capitals: true),
    FieldSpec('surcharge_per_kg', 'Extra per kg over the base', kind: FieldKind.decimal, min: 0, max: 1000, unit: 'Rs'),
  ],
);

final routes = Resource(
  icon: Icons.route_outlined,
  intro: 'Stations one truck serves in a single run, in order.',
  path: '/routes',
  singular: 'route',
  plural: 'Routes',
  titleKey: 'name',
  subtitle: (row) => (row['stops'] as List).join(' → '),
  fields: const [
    FieldSpec('name', 'Route name', mandatory: true),
    FieldSpec('stops', 'Stops in order, separated by commas', kind: FieldKind.list, mandatory: true, capitals: true, rule: city),
  ],
);
