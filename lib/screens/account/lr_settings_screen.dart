import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../widgets/common.dart';

/// Admin only: the LR number series and the values every new LR starts with.
class LrSettingsScreen extends StatefulWidget {
  const LrSettingsScreen({super.key});

  @override
  State<LrSettingsScreen> createState() => _LrSettingsScreenState();
}

class _LrSettingsScreenState extends State<LrSettingsScreen> with Submitter {
  final _prefix = TextEditingController();
  final _nextNumber = TextEditingController();
  final _fromCity = TextEditingController();
  final _stCharges = TextEditingController();
  bool _loaded = false;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_prefix, _nextNumber, _fromCity, _stCharges]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loadError = null);
    try {
      final s = await context.read<ApiClient>().get('/lrs/settings') as Map<String, dynamic>;
      if (!mounted) return;
      _prefix.text = s['prefix'] as String;
      _nextNumber.text = (s['next_number'] as int).toString();
      _fromCity.text = s['from_city'] as String? ?? '';
      _stCharges.text = s['default_st_charges'] as String;
      setState(() => _loaded = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  Future<void> _save() async {
    final from = _fromCity.text.trim();
    await context.read<ApiClient>().patch('/lrs/settings', {
      'prefix': _prefix.text.trim(),
      'next_number': int.parse(_nextNumber.text.trim()),
      'from_city': from.isEmpty ? null : from,
      'default_st_charges': _stCharges.text.trim(),
    });
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return Scaffold(
        appBar: AppBar(title: const Text('LR settings')),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                title: 'Could not load LR settings',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _load,
              ),
      );
    }
    return FormPage(
      title: 'LR settings',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Save',
      onSubmit: () => submit(_save),
      children: [
        AppTextField(
          label: 'Number prefix',
          controller: _prefix,
          mandatory: true,
          capitalization: TextCapitalization.characters,
        ),
        AppTextField(
          label: 'Next LR number',
          controller: _nextNumber,
          mandatory: true,
          keyboardType: TextInputType.number,
          check: (v) => (int.tryParse(v) ?? 0) > 0 ? null : 'Enter a whole number above 0',
        ),
        AppTextField(
          label: 'From city',
          controller: _fromCity,
          capitalization: TextCapitalization.characters,
        ),
        AppTextField(
          label: 'Default ST. charges',
          controller: _stCharges,
          mandatory: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          check: (v) => double.tryParse(v) == null ? 'Enter a number' : null,
        ),
      ],
    );
  }
}
