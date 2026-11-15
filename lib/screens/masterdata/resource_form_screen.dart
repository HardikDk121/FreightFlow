import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
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
  late bool _active;

  @override
  void initState() {
    super.initState();
    final row = widget.row;
    _texts = {
      for (final f in widget.resource.fields)
        if (f.kind != FieldKind.toggle) f.key: TextEditingController(text: _initialText(row?[f.key])),
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
        final num n => formatNumber(n),
        _ => value.toString(),
      };

  /// The request body: blank optional fields are sent as null so an edit can clear them.
  Map<String, dynamic> _body() => {
        for (final f in widget.resource.fields)
          f.key: switch (f.kind) {
            FieldKind.toggle => _toggles[f.key],
            FieldKind.decimal => double.tryParse(_texts[f.key]!.text.trim()),
            FieldKind.text => _texts[f.key]!.text.trim().isEmpty ? null : _texts[f.key]!.text.trim(),
          },
      };

  Future<void> _save() async {
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
      submitLabel: 'Save',
      onSubmit: () => submit(_save),
      children: [
        for (final f in widget.resource.fields)
          switch (f.kind) {
            FieldKind.toggle => SwitchField(
                label: f.label,
                value: _toggles[f.key]!,
                onChanged: (v) => setState(() => _toggles[f.key] = v),
              ),
            FieldKind.decimal => AppTextField(
                label: f.label,
                controller: _texts[f.key]!,
                mandatory: f.mandatory,
                check: f.check,
                unit: f.unit,
                keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
              ),
            FieldKind.text => AppTextField(
                label: f.label,
                controller: _texts[f.key]!,
                mandatory: f.mandatory,
                check: f.check,
                capitalization: f.capitals ? TextCapitalization.characters : TextCapitalization.words,
              ),
          },
        if (editing)
          SwitchField(label: 'Active', value: _active, onChanged: (v) => setState(() => _active = v)),
      ],
    );
  }
}
