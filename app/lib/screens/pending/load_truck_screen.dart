import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';

/// Load a truck for one stop or a run of stops: pick the truck, take the planner's suggestion or
/// set the packages by hand, then dispatch. Nothing is saved until Dispatch. Pops with `true` once dispatched.
class LoadTruckScreen extends StatefulWidget {
  const LoadTruckScreen({super.key, required this.stops, this.truckId, this.loads = const {}});

  /// The stations the truck will visit, in order.
  final List<String> stops;

  /// A truck and packages per LR id to start from, when opened from a suggestion.
  final String? truckId;
  final Map<String, int> loads;

  @override
  State<LoadTruckScreen> createState() => _LoadTruckScreenState();
}

class _LoadTruckScreenState extends State<LoadTruckScreen> with Submitter {
  final _driverName = TextEditingController();
  final _driverPhone = TextEditingController();
  late List<String> _stops = widget.stops;
  late String? _truckId = widget.truckId;
  List<Map<String, dynamic>>? _trucks;

  /// Saved routes that pass through the starting stop, offered so more drops can ride along.
  List<Map<String, dynamic>> _routes = const [];
  String _routeId = '';
  List<Map<String, dynamic>> _lrs = const [];
  String? _loadError;

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
      final routes = await api.get('/routes', query: {'limit': '200'}) as List;
      final lrs = await _pendingFor(_stops);
      if (!mounted) return;
      setState(() {
        _trucks = trucks.cast<Map<String, dynamic>>();
        _routes = [
          for (final r in routes.cast<Map<String, dynamic>>())
            if (widget.stops.length == 1 && (r['stops'] as List).contains(widget.stops.single)) r,
        ];
        _setLrs(lrs, widget.loads);
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  Future<List<Map<String, dynamic>>> _pendingFor(List<String> stops) async {
    final lrs = await context.read<ApiClient>().get('/pending/lrs', query: {'destination': stops.join(',')}) as List;
    return lrs.cast<Map<String, dynamic>>();
  }

  void _setLrs(List<Map<String, dynamic>> lrs, Map<String, int> loads) {
    for (final c in _load.values) {
      c.dispose();
    }
    _load.clear();
    _lrs = lrs;
    for (final lr in lrs) {
      final id = lr['lr_id'] as String;
      _load[id] = TextEditingController(text: '${loads[id] ?? 0}')..addListener(_recount);
    }
  }

  /// Switch between this stop alone and a whole saved route, and list the goods for it.
  Future<void> _chooseRoute(String routeId) async {
    final stops = routeId.isEmpty
        ? widget.stops
        : (_routes.firstWhere((r) => r['id'] == routeId)['stops'] as List).cast<String>();
    try {
      final lrs = await _pendingFor(stops);
      if (!mounted) return;
      setState(() {
        _routeId = routeId;
        _stops = stops;
        _plan = null;
        _setLrs(lrs, const {});
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  /// Ask the planner what fits, and put its suggestion in the package boxes.
  Future<void> _suggest() async {
    setState(() {
      _planning = true;
      error = null;
    });
    try {
      final plan = await context.read<ApiClient>().post('/trips/plan', {'truck_id': _truckId, 'stops': _stops})
          as Map<String, dynamic>;
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
      throw const ApiException(0, 'Choose a truck and load at least one package.');
    }
    final name = _driverName.text.trim();
    final phone = _driverPhone.text.trim();
    await context.read<ApiClient>().post('/trips', {
      'truck_id': _truckId,
      'stops': _stops,
      if (name.isNotEmpty) 'driver_name': name,
      if (phone.isNotEmpty) 'driver_phone': phone,
      'lines': lines,
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Truck dispatched to ${_stops.join(', ')}.')));
    Navigator.of(context).pop(true);
  }

  /// Redraw the selection summary and capacity as package counts change.
  void _recount() {
    if (mounted) setState(() {});
  }

  int _count(Map<String, dynamic> lr) => int.tryParse(_load[lr['lr_id']]!.text.trim()) ?? 0;

  /// Weight of what is selected, from each LR's pending weight spread over its pending packages.
  double get _selectedWeight => _lrs.fold(0, (sum, lr) {
        final pending = lr['pending'] as int;
        return sum + double.parse(lr['weight_kg'] as String) / pending * _count(lr).clamp(0, pending).toDouble();
      });

  Map<String, dynamic>? get _truck => _trucks?.where((t) => t['id'] == _truckId).firstOrNull;

  /// Why Dispatch is not possible yet, in words; empty when it is. The server checks the same.
  List<String> _blockers() {
    final today = DateUtils.dateOnly(DateTime.now());
    final truck = _truck;
    bool expired(String? iso) => iso != null && DateTime.parse(iso).isBefore(today);
    final missingBills = _lrs.where((lr) => _count(lr) > 0 && lr['ewb_status'] == 'pending').length;
    return [
      if (truck == null) 'Choose a truck.',
      if (truck != null && expired(truck['insurance_expiry'] as String?)) 'The truck\'s insurance has expired.',
      if (truck != null && expired(truck['fitness_expiry'] as String?)) 'The truck\'s fitness certificate has expired.',
      if (missingBills > 0) 'Add the e-way bill to $missingBills selected LR${missingBills == 1 ? '' : 's'}.',
      if (_lrs.every((lr) => _count(lr) == 0)) 'Select at least one LR.',
    ];
  }

  String? _checkLoad(String value, int pending) {
    final n = int.tryParse(value);
    if (n == null || n < 0) return 'Whole number';
    return n > pending ? 'Only $pending pending' : null;
  }


  /// Green when valid, red when expired, grey when not recorded.
  StatusChip _paperChip(String name, String? iso) {
    if (iso == null) return StatusChip.tone('$name not recorded', Tone.neutral);
    final expired = DateTime.parse(iso).isBefore(DateUtils.dateOnly(DateTime.now()));
    return StatusChip.tone(expired ? '$name expired' : '$name valid', expired ? Tone.danger : Tone.success);
  }

  Widget _hero() {
    final truck = _truck;
    final from = truck?['current_station'] as String?;
    return HeroHeader(
      showBack: true,
      eyebrow: _stops.length == 1 ? 'Destination' : 'Drops, in order',
      title: _stops.join(' → '),
      subtitle: from == null ? 'Load planner' : 'Truck is at $from',
      trailing: const Icon(Icons.local_shipping_outlined, color: Palette.primary, size: 30),
      child: truck == null ? null : StatusChip.tone(truck['vehicle_number'] as String, Tone.dark),
    );
  }

  Widget _trucksPicker(List<Map<String, dynamic>> trucks) {
    final text = Theme.of(context).textTheme;
    if (trucks.isEmpty) {
      return const Padding(
        padding: EdgeInsets.only(bottom: 16),
        child: ErrorBanner('No trucks yet. Add one under Account, Master data, Trucks.'),
      );
    }
    return SizedBox(
      height: 64,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: trucks.length,
        separatorBuilder: (_, __) => const SizedBox(width: 10),
        itemBuilder: (_, i) {
          final t = trucks[i];
          final selected = t['id'] == _truckId;
          return Material(
            color: selected ? Palette.ink : Palette.surface,
            borderRadius: BorderRadius.circular(18),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: () => setState(() {
                _truckId = t['id'] as String;
                _plan = null;
              }),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      t['vehicle_number'] as String,
                      style: text.labelLarge!.copyWith(color: selected ? Palette.onInk : Palette.onSurface),
                    ),
                    Text(
                      '${kgLabel(t['payload_kg'] as num)}${t['current_station'] == null ? '' : ' · at ${t['current_station']}'}',
                      style: text.bodySmall!.copyWith(color: selected ? Palette.onInkMuted : Palette.onSurfaceMuted),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  /// Payload follows the selection live; space comes from the planner, which knows package sizes.
  Widget _capacity() {
    final truck = _truck;
    if (truck == null) return const SizedBox.shrink();
    final payload = (truck['payload_kg'] as num).toDouble();
    final weight = _selectedWeight;
    final plan = _plan;
    return DarkPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          MeterBar(
            label: 'Payload weight',
            detail: '${kgLabel(weight.round())} of ${kgLabel(payload)}',
            percent: (weight * 100 / payload).round(),
          ),
          if (plan != null)
            MeterBar(
              label: 'Usable volume · 85% safety cap',
              detail: '${plan['volume_used_m3']} of ${plan['usable_volume_m3']} m³ usable, for the suggested load',
              percent: plan['volume_used_pct'] as int,
            )
          else
            Text(
              'Tap "Suggest a load" to check space as well. It needs package types on the LRs.',
              style: onInk(Theme.of(context).textTheme.bodySmall!, muted: true),
            ),
          if (plan != null && ((plan['weight_only'] as List).isNotEmpty || (plan['unsized'] as List).isNotEmpty))
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'Some LRs have no package type, so their space is not counted.',
                style: onInk(Theme.of(context).textTheme.bodySmall!, muted: true),
              ),
            ),
        ],
      ),
    );
  }

  Widget _lrCard(Map<String, dynamic> lr) {
    final text = Theme.of(context).textTheme;
    final pending = lr['pending'] as int;
    final count = _count(lr);
    final selected = count > 0;
    final controller = _load[lr['lr_id']]!;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        padding: const EdgeInsets.fromLTRB(8, 12, 16, 16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Checkbox(
              value: selected,
              onChanged: (on) => controller.text = on == true ? '$pending' : '0',
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 10),
                  Text('${lr['lr_number']} · ${(lr['to_city'] as String).toUpperCase()}', style: text.titleMedium),
                  const SizedBox(height: 2),
                  Text('${lr['consignor_name']} → ${lr['consignee_name']}', style: text.bodySmall),
                  Text(
                    '$pending pkgs · ${kgLabel(double.parse(lr['weight_kg'] as String))} · ${lr['freight_by']}'
                    ' · ${waitingLabel(lr['days_waiting'] as int)}',
                    style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                  ),
                  if (lr['ewb_status'] == 'pending') ...[
                    const SizedBox(height: 8),
                    StatusChip.tone('EWB missing', Tone.danger),
                  ],
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      SizedBox(
                        width: 104,
                        child: TextFormField(
                          controller: controller,
                          keyboardType: TextInputType.number,
                          textAlign: TextAlign.center,
                          style: text.titleMedium,
                          decoration: InputDecoration(
                            suffixText: '/$pending',
                            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(999)),
                            enabledBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(999),
                              borderSide: const BorderSide(color: Palette.outline),
                            ),
                          ),
                          validator: (v) => _checkLoad(v?.trim() ?? '', pending),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          count >= pending ? 'all packages' : '${pending - count.clamp(0, pending)} stay pending',
                          style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
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
        appBar: AppBar(title: const Text('Load planner')),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                title: 'Could not load trucks and pending goods',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _loadData,
                tone: Tone.danger,
              ),
      );
    }
    final text = Theme.of(context).textTheme;
    final truck = _truck;
    final selected = _lrs.where((lr) => _count(lr) > 0).toList();
    final packages = selected.fold<int>(0, (n, lr) => n + _count(lr));
    final missingBills = _lrs.where((lr) => lr['ewb_status'] == 'pending').length;
    final blockers = _blockers();
    return FormPage(
      title: 'Load planner',
      hero: _hero(),
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Dispatch',
      onSubmit: blockers.isEmpty ? () => submit(_dispatch) : null,
      footer: blockers.isEmpty
          ? null
          : Text(blockers.join(' '), style: text.bodySmall!.copyWith(color: Palette.error)),
      children: [
        if (truck != null || missingBills > 0)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (missingBills > 0) StatusChip.tone('$missingBills EWB missing', Tone.danger),
                if (truck != null) _paperChip('Insurance', truck['insurance_expiry'] as String?),
                if (truck != null) _paperChip('Fitness certificate', truck['fitness_expiry'] as String?),
              ],
            ),
          ),
        _capacity(),
        if (_routes.isNotEmpty) ...[
          const SizedBox(height: 16),
          ChoiceField<String>(
            label: 'Drop at',
            options: {
              '': 'Only ${widget.stops.single}',
              for (final r in _routes) r['id'] as String: (r['stops'] as List).join(' → '),
            },
            value: _routeId,
            onChanged: _chooseRoute,
          ),
        ],
        const SectionHeader('Truck', icon: Icons.local_shipping_outlined),
        _trucksPicker(trucks),
        const SizedBox(height: 16),
        _pairFields(
          AppTextField(label: 'Driver name', controller: _driverName, capitalization: TextCapitalization.words),
          AppTextField(label: 'Driver phone', controller: _driverPhone, keyboardType: TextInputType.phone),
        ),
        OutlinedButton.icon(
          onPressed: _truckId == null || _planning ? null : _suggest,
          icon: const Icon(Icons.auto_awesome_outlined),
          label: Text(_planning ? 'Planning…' : 'Suggest a load'),
        ),
        SectionHeader(
          'Select lorry receipts',
          icon: Icons.checklist_rounded,
          trailing: Text('${_lrs.length} available', style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
        ),
        if (_lrs.isEmpty) MessageView(card: true, icon: Icons.inbox_outlined, title: 'Nothing waiting', body: 'No pending LR is for these stops.'),
        for (final lr in _lrs) _lrCard(lr),
        if (selected.isNotEmpty)
          DarkPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${selected.length} LR${selected.length == 1 ? '' : 's'} selected', style: onInk(text.titleMedium!)),
                const SizedBox(height: 2),
                Text('$packages packages · ${kgLabel(_selectedWeight.round())}', style: onInk(text.bodySmall!, muted: true)),
              ],
            ),
          ),
      ],
    );
  }

  Widget _pairFields(Widget left, Widget right) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [Expanded(child: left), const SizedBox(width: 12), Expanded(child: right)],
      );
}
