import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'resource.dart';

/// Add ([row] is null) or edit one row of a resource. Pops with `true` after a save.
class ResourceFormScreen extends StatefulWidget {
  const ResourceFormScreen({super.key, required this.resource, this.row});

  final Resource resource;
  final JsonRow? row;

  @override
  State<ResourceFormScreen> createState() => _ResourceFormScreenState();
}

class _ResourceFormScreenState extends State<ResourceFormScreen> with Submitter {
  late final Map<String, TextEditingController> _texts;
  late final Map<String, bool> _toggles;

  /// Date fields as ISO dates ("2027-03-31"); null until picked.
  late final Map<String, String?> _dates;
  late bool _active;

  @override
  void initState() {
    super.initState();
    final row = widget.row;
    _texts = {
      for (final f in widget.resource.fields)
        if (f.kind == FieldKind.text || f.kind == FieldKind.decimal || f.kind == FieldKind.list)
          f.key: TextEditingController(text: _initialText(row?[f.key])),
    };
    _dates = {
      for (final f in widget.resource.fields)
        if (f.kind == FieldKind.date) f.key: row?[f.key] as String?,
    };
    _toggles = {
      for (final f in widget.resource.fields)
        if (f.kind == FieldKind.toggle) f.key: row?[f.key] as bool? ?? true,
    };
    _active = row?['is_active'] as bool? ?? true;
  }

  @override
  void dispose() {
    for (final c in _texts.values) {
      c.dispose();
    }
    super.dispose();
  }

  static String _initialText(Object? value) => switch (value) {
        null => '',
        final List<dynamic> items => items.join(', '),
        final num n => formatNumber(n),
        _ => value.toString(),
      };

  /// The request body: blank optional fields are sent as null so an edit can clear them.
  Map<String, dynamic> _body() => {
        for (final f in widget.resource.fields)
          f.key: switch (f.kind) {
            FieldKind.toggle => _toggles[f.key],
            FieldKind.date => _dates[f.key],
            FieldKind.list => [
                for (final item in _texts[f.key]!.text.split(','))
                  if (item.trim().isNotEmpty) item.trim(),
              ],
            FieldKind.decimal => double.tryParse(_texts[f.key]!.text.trim()),
            FieldKind.text => _texts[f.key]!.text.trim().isEmpty ? null : _texts[f.key]!.text.trim(),
          },
      };

  Future<void> _pickDate(FieldSpec f) async {
    final current = _dates[f.key];
    final picked = await showDatePicker(
      context: context,
      initialDate: current == null ? DateTime.now() : DateTime.parse(current),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (picked != null) setState(() => _dates[f.key] = picked.toIso8601String().substring(0, 10));
  }

  static String _dateLabel(String iso) {
    final parts = iso.split('-');
    return '${parts[2]}-${parts[1]}-${parts[0]}';
  }

  Widget _dateField(FieldSpec f) {
    final value = _dates[f.key];
    final expired = value != null && DateTime.parse(value).isBefore(DateUtils.dateOnly(DateTime.now()));
    return PickerField(
      label: f.label,
      mandatory: f.mandatory,
      value: value == null ? null : _dateLabel(value),
      placeholder: 'DD-MM-YYYY',
      icon: Icons.calendar_today_outlined,
      onTap: () => _pickDate(f),
      note: expired ? 'This date has passed.' : null,
      noteTone: Tone.danger,
    );
  }


  Future<void> _save() async {
    final missing = [
      for (final f in widget.resource.fields)
        if (f.kind == FieldKind.date && f.mandatory && _dates[f.key] == null) f.label,
    ];
    if (missing.isNotEmpty) throw ApiException(0, 'Choose a date for: ${missing.join(', ')}.');
    final api = context.read<ApiClient>();
    final row = widget.row;
    if (row == null) {
      await api.post(widget.resource.path, _body());
    } else {
      await api.patch('${widget.resource.path}/${row['id']}', {..._body(), 'is_active': _active});
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.row != null;
    return FormPage(
      title: '${editing ? 'Edit' : 'Add'} ${widget.resource.singular}',
      formKey: formKey,
      busy: busy,
      error: error,
      subtitle: widget.resource.intro,
      submitLabel: 'Save',
      onSubmit: () => submit(_save),
      children: [
        for (final group in _rows())
          group.length == 1
              ? _input(group.single)
              : Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (var i = 0; i < group.length; i++) ...[
                      if (i > 0) const SizedBox(width: 10),
                      Expanded(child: _input(group[i])),
                    ],
                  ],
                ),
        if (editing)
          SwitchField(label: 'Active', value: _active, onChanged: (v) => setState(() => _active = v)),
      ],
    );
  }

  /// The fields, with neighbours that share a [FieldSpec.row] gathered onto one line.
  List<List<FieldSpec>> _rows() {
    final rows = <List<FieldSpec>>[];
    for (final f in widget.resource.fields) {
      if (f.row != null && rows.isNotEmpty && rows.last.first.row == f.row) {
        rows.last.add(f);
      } else {
        rows.add([f]);
      }
    }
    return rows;
  }

  Widget _input(FieldSpec f) => switch (f.kind) {
        FieldKind.date => _dateField(f),
        FieldKind.toggle => SwitchField(
            label: f.label,
            subtitle: f.helper,
            value: _toggles[f.key]!,
            onChanged: (v) => setState(() => _toggles[f.key] = v),
          ),
        FieldKind.decimal => AppTextField(
            label: f.label,
            controller: _texts[f.key]!,
            mandatory: f.mandatory,
            check: f.check,
            unit: f.unit,
            hint: f.hint,
            helper: f.helper,
            keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
          ),
        FieldKind.text || FieldKind.list => AppTextField(
            label: f.label,
            controller: _texts[f.key]!,
            mandatory: f.mandatory,
            check: f.check,
            hint: f.hint,
            helper: f.helper,
            capitalization: f.capitals ? TextCapitalization.characters : TextCapitalization.words,
          ),
      };
}
