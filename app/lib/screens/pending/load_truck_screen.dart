import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';

/// Load a truck for one destination: pick the truck, take the planner's suggestion or set the
/// packages by hand, then dispatch. Nothing is saved until Dispatch. Pops with `true` once dispatched.
class LoadTruckScreen extends StatefulWidget {
  const LoadTruckScreen({super.key, required this.city});

  final String city;

  @override
  State<LoadTruckScreen> createState() => _LoadTruckScreenState();
}

class _LoadTruckScreenState extends State<LoadTruckScreen> with Submitter {
  final _driverName = TextEditingController();
  final _driverPhone = TextEditingController();
  List<Map<String, dynamic>>? _trucks;
  List<Map<String, dynamic>> _lrs = const [];
  String? _loadError;
  String? _truckId;

  /// Packages to load, per LR id. One controller per pending LR.
  final Map<String, TextEditingController> _load = {};
  Map<String, dynamic>? _plan;
  bool _planning = false;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  @override
  void dispose() {
    _driverName.dispose();
    _driverPhone.dispose();
    for (final c in _load.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() => _loadError = null);
    final api = context.read<ApiClient>();
    try {
      final trucks = await api.get('/trucks', query: {'limit': '200'}) as List;
      final lrs = await api.get('/pending/lrs', query: {'destination': widget.city}) as List;
      if (!mounted) return;
      setState(() {
        _trucks = trucks.cast<Map<String, dynamic>>();
        _lrs = lrs.cast<Map<String, dynamic>>();
        for (final lr in _lrs) {
          _load[lr['lr_id'] as String] = TextEditingController(text: '0');
        }
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  /// Ask the planner what fits, and put its suggestion in the package boxes.
  Future<void> _suggest() async {
    setState(() {
      _planning = true;
      error = null;
    });
    try {
      final plan = await context.read<ApiClient>().post('/trips/plan', {
        'truck_id': _truckId,
        'destination': widget.city,
      }) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _plan = plan;
        for (final c in _load.values) {
          c.text = '0';
        }
        for (final line in (plan['lines'] as List).cast<Map<String, dynamic>>()) {
          _load[line['lr_id']]?.text = '${line['load']}';
        }
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => _planning = false);
    }
  }

  Future<void> _dispatch() async {
    final lines = [
      for (final lr in _lrs)
        if ((int.tryParse(_load[lr['lr_id']]!.text.trim()) ?? 0) > 0)
          {'lr_id': lr['lr_id'], 'packages': int.parse(_load[lr['lr_id']]!.text.trim())},
    ];
    if (_truckId == null || lines.isEmpty) {
      setState(() => error = 'Choose a truck and load at least one package.');
      return;
    }
    final name = _driverName.text.trim();
    final phone = _driverPhone.text.trim();
    await context.read<ApiClient>().post('/trips', {
      'truck_id': _truckId,
      'destination': widget.city,
      if (name.isNotEmpty) 'driver_name': name,
      if (phone.isNotEmpty) 'driver_phone': phone,
      'lines': lines,
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Truck dispatched to ${widget.city}.')));
    Navigator.of(context).pop(true);
  }

  String? _checkLoad(String value, int pending) {
    final n = int.tryParse(value);
    if (n == null || n < 0) return 'Whole number';
    return n > pending ? 'Only $pending pending' : null;
  }

  Widget _bar(String label, int percent, String detail) {
    final text = Theme.of(context).textTheme;
    final over = percent > 100;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(label, style: text.labelMedium)),
              Text('$percent%', style: text.titleMedium!.copyWith(color: over ? Palette.error : null)),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: (percent / 100).clamp(0, 1).toDouble(),
              minHeight: 8,
              backgroundColor: Palette.background,
              color: over ? Palette.error : Palette.primary,
            ),
          ),
          const SizedBox(height: 4),
          Text(detail, style: text.bodySmall!.copyWith(color: StatusColors.of(context).muted)),
        ],
      ),
    );
  }

  Widget _planSummary(Map<String, dynamic> plan) {
    final text = Theme.of(context).textTheme;
    final skipped = [
      for (final lr in (plan['unsized'] as List)) '${lr['lr_number']} (no package type)',
      for (final lr in (plan['too_big'] as List)) '${lr['lr_number']} (too big for this truck)',
    ];
    return AppCard(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text("Planner's suggestion", style: text.titleMedium),
            const SizedBox(height: 12),
            _bar('Space', plan['volume_used_pct'] as int,
                '${plan['volume_used_m3']} of ${plan['usable_volume_m3']} m³ usable'),
            _bar('Weight', plan['payload_used_pct'] as int,
                '${plan['weight_used_kg']} of ${plan['payload_kg']} kg payload'),
            if (skipped.isNotEmpty)
              Text(
                'Not planned, set by hand: ${skipped.join(', ')}',
                style: text.bodyMedium!.copyWith(color: Palette.warning),
              ),
            Text(
              'Advice only. Loaders decide what physically fits.',
              style: text.bodySmall!.copyWith(color: StatusColors.of(context).muted),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final trucks = _trucks;
    if (trucks == null) {
      return Scaffold(
        appBar: AppBar(title: Text('Truck for ${widget.city}')),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                title: 'Could not load trucks and pending goods',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _loadData,
              ),
      );
    }
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Truck for ${widget.city}',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Dispatch',
      onSubmit: () => submit(_dispatch),
      children: [
        if (trucks.isEmpty)
          const Padding(
            padding: EdgeInsets.only(bottom: 16),
            child: ErrorBanner('No trucks yet. Add one under Account, Master data, Trucks.'),
          )
        else
          ChoiceField<String?>(
            label: 'Truck',
            options: {for (final t in trucks) t['id'] as String: t['vehicle_number'] as String},
            value: _truckId,
            onChanged: (id) => setState(() {
              _truckId = id;
              _plan = null;
            }),
          ),
        AppTextField(label: 'Driver name', controller: _driverName, capitalization: TextCapitalization.words),
        AppTextField(label: 'Driver phone', controller: _driverPhone, keyboardType: TextInputType.phone),
        OutlinedButton.icon(
          onPressed: _truckId == null || _planning ? null : _suggest,
          icon: const Icon(Icons.auto_awesome_outlined),
          label: Text(_planning ? 'Planning…' : 'Suggest a load'),
        ),
        const SizedBox(height: 16),
        if (_plan != null) ...[_planSummary(_plan!), const SizedBox(height: 16)],
        Text('Packages to load, oldest first', style: text.titleMedium),
        const SizedBox(height: 12),
        for (final lr in _lrs)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: AppCard(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('${lr['lr_number']} · ${lr['consignee_name']}', style: text.titleMedium),
                          const SizedBox(height: 4),
                          Text(
                            '${lr['pending']} pending · ${waitingLabel(lr['days_waiting'] as int)}',
                            style: text.bodyMedium,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    SizedBox(
                      width: 96,
                      child: TextFormField(
                        controller: _load[lr['lr_id']],
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        style: text.bodyLarge,
                        validator: (v) => _checkLoad(v?.trim() ?? '', lr['pending'] as int),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}
