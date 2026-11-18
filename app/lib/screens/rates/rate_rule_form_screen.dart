import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../widgets/common.dart';
import '../masterdata/resource.dart';

const _methods = {
  'per_kg': 'Per kg',
  'per_package_slab': 'Per package, by its weight',
  'per_unit': 'Per package, flat',
};

String _rateSummary(JsonRow row) => switch (row['method']) {
      'per_kg' => 'Rs ${formatNumber(row['rate'] as num)} per kg',
      'per_unit' => 'Rs ${formatNumber(row['rate'] as num)} per package',
      _ => [
          for (final slab in (row['slabs'] as List))
            'up to ${formatNumber(slab['up_to_kg'] as num)} kg Rs ${formatNumber(slab['amount'] as num)}',
        ].join(', '),
    };

/// The rate matrix: how freight is charged for each class of goods in each zone.
final rateRules = Resource(
  path: '/rate-rules',
  singular: 'rate',
  plural: 'Rates',
  titleKey: 'goods_class',
  subtitle: (row) => '${row['zone']} zone · ${_rateSummary(row)}',
  fields: const [],
  icon: Icons.price_change_outlined,
  intro: 'How freight is charged for one class of goods in one zone.',
  customForm: (row) => RateRuleFormScreen(row: row),
);

/// Add or edit one rate. Pops with `true` after a save.
class RateRuleFormScreen extends StatefulWidget {
  const RateRuleFormScreen({super.key, this.row});

  final JsonRow? row;

  @override
  State<RateRuleFormScreen> createState() => _RateRuleFormScreenState();
}

class _RateRuleFormScreenState extends State<RateRuleFormScreen> with Submitter {
  late final _goodsClass = TextEditingController(text: widget.row?['goods_class'] as String? ?? '');
  late final _zone = TextEditingController(text: widget.row?['zone'] as String? ?? '');
  late final _rate = TextEditingController(
    text: widget.row?['rate'] == null ? '' : formatNumber(widget.row!['rate'] as num),
  );
  late final _slabs = TextEditingController(
    text: [
      for (final slab in (widget.row?['slabs'] as List? ?? const []))
        '${formatNumber(slab['up_to_kg'] as num)}=${formatNumber(slab['amount'] as num)}',
    ].join(', '),
  );
  late String _method = widget.row?['method'] as String? ?? 'per_kg';
  late bool _active = widget.row?['is_active'] as bool? ?? true;

  @override
  void dispose() {
    for (final c in [_goodsClass, _zone, _rate, _slabs]) {
      c.dispose();
    }
    super.dispose();
  }

  /// "35=350, 40=400" -> [{up_to_kg: 35, amount: 350}, {up_to_kg: 40, amount: 400}], or null if malformed.
  static List<Map<String, double>>? _parseSlabs(String text) {
    final slabs = <Map<String, double>>[];
    for (final part in text.split(',')) {
      if (part.trim().isEmpty) continue;
      final pair = part.split(RegExp('[=:]'));
      final limit = pair.length == 2 ? double.tryParse(pair[0].trim()) : null;
      final amount = pair.length == 2 ? double.tryParse(pair[1].trim()) : null;
      if (limit == null || amount == null || limit <= 0 || amount <= 0) return null;
      slabs.add({'up_to_kg': limit, 'amount': amount});
    }
    return slabs.isEmpty ? null : slabs;
  }

  Future<void> _save() async {
    final api = context.read<ApiClient>();
    final slab = _method == 'per_package_slab';
    final body = <String, dynamic>{
      'goods_class': _goodsClass.text.trim(),
      'zone': _zone.text.trim(),
      'method': _method,
      'rate': slab ? null : double.parse(_rate.text.trim()),
      'slabs': slab ? _parseSlabs(_slabs.text) : null,
    };
    final row = widget.row;
    if (row == null) {
      await api.post('/rate-rules', body);
    } else {
      await api.patch('/rate-rules/${row['id']}', {...body, 'is_active': _active});
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.row != null;
    return FormPage(
      title: editing ? 'Edit rate' : 'Add rate',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Save',
      onSubmit: () => submit(_save),
      children: [
        AppTextField(
          label: 'Class of goods',
          controller: _goodsClass,
          mandatory: true,
          capitalization: TextCapitalization.sentences,
          helper: 'For example Bearings, Halka maal, Rolls and sheets.',
        ),
        AppTextField(
          label: 'Zone (base station)',
          controller: _zone,
          mandatory: true,
          capitalization: TextCapitalization.characters,
          helper: 'Stations set to this zone use this rate, plus their own extra per kg.',
        ),
        ChoiceField<String>(
          label: 'Charged',
          options: _methods,
          value: _method,
          onChanged: (m) => setState(() => _method = m),
        ),
        if (_method == 'per_package_slab')
          AppTextField(
            label: 'Slabs',
            controller: _slabs,
            mandatory: true,
            lines: 2,
            helper: 'Package weight up to = amount, separated by commas. Example: 35=350, 40=400',
            check: (v) => _parseSlabs(v) == null ? 'Write each slab as weight=amount, like 35=350' : null,
          )
        else
          AppTextField(
            label: _method == 'per_kg' ? 'Rate per kg' : 'Rate per package',
            controller: _rate,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter a rate above 0',
          ),
        if (editing) SwitchField(label: 'Active', value: _active, onChanged: (v) => setState(() => _active = v)),
      ],
    );
  }
}
