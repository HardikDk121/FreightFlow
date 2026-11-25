import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../validation.dart';
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
  final _holdDays = TextEditingController();
  final _cashLimit = TextEditingController();
  final _receiptPrefix = TextEditingController();
  final _nextReceipt = TextEditingController();
  final _gatePassPrefix = TextEditingController();
  final _nextGatePass = TextEditingController();
  String _creditFrom = 'delivery';
  DateTime? _controlsFrom;
  bool _loaded = false;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [
      _prefix, _nextNumber, _fromCity, _stCharges, _holdDays, _cashLimit,
      _receiptPrefix, _nextReceipt, _gatePassPrefix, _nextGatePass,
    ]) {
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
      _holdDays.text = '${s['overdue_hold_days']}';
      _cashLimit.text = s['collector_cash_limit'] as String;
      _receiptPrefix.text = s['receipt_prefix'] as String;
      _nextReceipt.text = '${s['next_receipt_number']}';
      _gatePassPrefix.text = s['gate_pass_prefix'] as String;
      _nextGatePass.text = '${s['next_gate_pass_number']}';
      _creditFrom = s['credit_from'] as String;
      final controls = s['credit_controls_from'] as String?;
      _controlsFrom = controls == null ? null : DateTime.parse(controls);
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
      'credit_from': _creditFrom,
      'overdue_hold_days': int.parse(_holdDays.text.trim()),
      'collector_cash_limit': _cashLimit.text.trim(),
      'credit_controls_from': _controlsFrom?.toIso8601String().substring(0, 10),
      'receipt_prefix': _receiptPrefix.text.trim(),
      'next_receipt_number': int.parse(_nextReceipt.text.trim()),
      'gate_pass_prefix': _gatePassPrefix.text.trim(),
      'next_gate_pass_number': int.parse(_nextGatePass.text.trim()),
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
      subtitle: 'Receipt numbering and booking defaults.',
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
          check: city,
          capitalization: TextCapitalization.characters,
        ),
        AppTextField(
          label: 'Default ST. charges',
          controller: _stCharges,
          mandatory: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          check: (v) => double.tryParse(v) == null ? 'Enter a number' : null,
        ),
        const SectionHeader('Money receipt and gate pass numbers', icon: Icons.numbers),
        Text(
          'To continue your paper pads, leave the prefix empty and enter the next number on the pad.',
          style: Theme.of(context).textTheme.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
        ),
        const SizedBox(height: 12),
        for (final (label, prefix, next) in [
          ('Money receipt', _receiptPrefix, _nextReceipt),
          ('Gate pass', _gatePassPrefix, _nextGatePass),
        ])
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: AppTextField(
                  label: '$label prefix',
                  controller: prefix,
                  capitalization: TextCapitalization.characters,
                  check: (v) => RegExp(r'^[A-Za-z]{0,6}$').hasMatch(v) ? null : 'Up to 6 letters',
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: AppTextField(
                  label: 'Next number',
                  controller: next,
                  mandatory: true,
                  keyboardType: TextInputType.number,
                  check: (v) => (int.tryParse(v) ?? 0) > 0 ? null : 'Above 0',
                ),
              ),
            ],
          ),
        const SectionHeader('Credit and collection', icon: Icons.account_balance_wallet_outlined),
        ChoiceField<String>(
          label: 'Credit days count from',
          options: const {'delivery': 'Delivery', 'booking': 'Booking'},
          value: _creditFrom,
          onChanged: (v) => setState(() => _creditFrom = v),
        ),
        PickerField(
          label: 'Hold bookings from',
          mandatory: false,
          value: _controlsFrom == null ? null : dayLabel(_controlsFrom!.toIso8601String().substring(0, 10)),
          placeholder: 'Off',
          icon: Icons.calendar_today_outlined,
          onTap: () async {
            final now = DateTime.now();
            final picked = await showDatePicker(
              context: context,
              firstDate: DateTime(now.year - 2),
              lastDate: now,
              initialDate: _controlsFrom ?? now,
            );
            if (picked != null) setState(() => _controlsFrom = picked);
          },
          note: 'From this date, a customer over their credit limit, or with money overdue, '
              'cannot be booked without the owner. Older LRs are not counted, because their payments may not be in the app.',
        ),
        if (_controlsFrom != null)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(onPressed: () => setState(() => _controlsFrom = null), child: const Text('Turn holds off')),
          ),
        AppTextField(
          label: 'Hold after overdue by',
          controller: _holdDays,
          mandatory: true,
          unit: 'days',
          keyboardType: TextInputType.number,
          check: (v) {
            final n = int.tryParse(v);
            return n == null || n < 0 || n > 365 ? 'Between 0 and 365' : null;
          },
        ),
        AppTextField(
          label: 'Most cash a collector may take on one receipt',
          controller: _cashLimit,
          mandatory: true,
          unit: 'Rs',
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter an amount above 0',
        ),
      ],
    );
  }
}
