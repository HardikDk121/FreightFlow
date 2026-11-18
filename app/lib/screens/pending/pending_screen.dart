import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../home/home_screen.dart' show DestinationCard;
import '../shell.dart';
import 'load_truck_screen.dart';

typedef _Rows = List<Map<String, dynamic>>;

/// What is waiting in the godown: the totals, suggested truck loads, then every destination.
class PendingScreen extends StatefulWidget {
  const PendingScreen({super.key});

  @override
  State<PendingScreen> createState() => _PendingScreenState();
}

class _PendingScreenState extends State<PendingScreen> {
  final _loader = GlobalKey<LoaderState<(_Rows, _Rows)>>();

  /// Destinations for everyone; truck suggestions only for those who can dispatch.
  Future<(_Rows, _Rows)> _load() async {
    final api = context.read<ApiClient>();
    final canDispatch = context.read<Session>().user?.canDispatch ?? false;
    final destinations = (await api.get('/pending') as List).cast<Map<String, dynamic>>();
    final suggestions = canDispatch
        ? (await api.get('/trips/suggestions') as List).cast<Map<String, dynamic>>()
        : <Map<String, dynamic>>[];
    return (destinations, suggestions);
  }

  Future<void> _loadTruck(Map<String, dynamic> suggestion) async {
    final plan = suggestion['plan'] as Map<String, dynamic>;
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => LoadTruckScreen(
          stops: (suggestion['stops'] as List).cast<String>(),
          truckId: suggestion['truck_id'] as String,
          loads: {for (final line in (plan['lines'] as List)) line['lr_id'] as String: line['load'] as int},
        ),
      ),
    );
    await _loader.currentState?.reload();
  }

  Widget _suggestionCard(Map<String, dynamic> s) {
    final text = Theme.of(context).textTheme;
    final stops = (s['stops'] as List).join(' → ');
    final hasTruck = s['truck_id'] != null;
    final days = s['oldest_days_waiting'] as int;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.local_shipping_outlined, color: Palette.onSurface),
                const SizedBox(width: 10),
                Expanded(child: Text(hasTruck ? s['vehicle_number'] as String : 'No free truck', style: text.titleMedium)),
                StatusChip.tone('Oldest ${waitingLabel(days)}', days > 3 ? Tone.warning : Tone.info),
              ],
            ),
            const SizedBox(height: 10),
            Text(stops, style: text.labelLarge),
            if (s['route_name'] != null || s['truck_location'] != null)
              Text(
                [
                  if (s['route_name'] != null) s['route_name'] as String,
                  if (s['truck_location'] != null) 'truck is at ${s['truck_location']}',
                ].join(' · '),
                style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
              ),
            const SizedBox(height: 8),
            Text(s['reason'] as String, style: text.bodyMedium),
            if (hasTruck) ...[
              const SizedBox(height: 14),
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(46)),
                onPressed: () => _loadTruck(s),
                child: const Text('Plan this load'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Pending goods')),
        body: Loader<(_Rows, _Rows)>(
          key: _loader,
          errorTitle: 'Could not load pending goods',
          load: _load,
          builder: (context, data) {
            final (destinations, suggestions) = data;
            final packages = destinations.fold<int>(0, (n, d) => n + (d['packages'] as int));
            final lrs = destinations.fold<int>(0, (n, d) => n + (d['lr_count'] as int));
            final weight = destinations.fold<double>(0, (n, d) => n + double.parse(d['weight_kg'] as String));
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, navBarClearance),
              children: [
                Align(
                  alignment: Alignment.centerLeft,
                  child: StatusChip.tone('$lrs LR${lrs == 1 ? '' : 's'} waiting', lrs == 0 ? Tone.success : Tone.info),
                ),
                const SizedBox(height: 8),
                const SectionLabel('Godown overview'),
                if (destinations.isEmpty)
                  MessageView(
                    card: true,
                    tone: Tone.success,
                    icon: Icons.check_rounded,
                    title: 'Nothing is waiting',
                    body: 'Every booked LR has been dispatched. Your godown is clear for the next load.',
                    actionLabel: 'View all trips',
                    onAction: () => ShellScope.of(context)?.goTo(ShellTab.trips),
                  ),
                const SizedBox(height: 12),
                AppCard(
                  padding: const EdgeInsets.all(18),
                  child: Row(
                    children: [
                      Expanded(child: MetricTile(value: '$packages', label: 'Packages waiting')),
                      Expanded(child: MetricTile(value: kgLabel(weight), label: 'Undispatched weight')),
                    ],
                  ),
                ),
                if (suggestions.isNotEmpty) ...[
                  const SectionHeader('Suggested loads', icon: Icons.auto_awesome_outlined),
                  for (final s in suggestions) _suggestionCard(s),
                ],
                if (destinations.isNotEmpty) ...[
                  const SectionHeader('By destination', icon: Icons.place_outlined),
                  for (final d in destinations) ...[
                    DestinationCard(destination: d, onReturn: () => _loader.currentState?.reload()),
                    const SizedBox(height: 12),
                  ],
                ],
              ],
            );
          },
        ),
      );
}

/// One pending LR: number, how long it has waited, parties, and what is left of it.
class PendingLrCard extends StatelessWidget {
  const PendingLrCard({super.key, required this.lr});

  final Map<String, dynamic> lr;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final days = lr['days_waiting'] as int;
    return AppCard(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(lr['lr_number'] as String, style: text.titleMedium)),
              StatusChip.tone(waitingLabel(days), days > 3 ? Tone.warning : Tone.info),
            ],
          ),
          const SizedBox(height: 8),
          Text('${lr['consignor_name']} → ${lr['consignee_name']}', style: text.bodyMedium),
          const SizedBox(height: 4),
          Text(
            '${lr['pending']} of ${lr['packages']} pkgs · ${kgLabel(double.parse(lr['weight_kg'] as String))}'
            ' · ${lr['goods_description']}',
            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
          ),
          if (lr['ewb_status'] == 'pending') ...[
            const SizedBox(height: 10),
            StatusChip.tone('EWB missing: cannot dispatch yet', Tone.danger),
          ],
        ],
      ),
    );
  }
}

/// The LRs waiting for one destination, oldest first, with how long each has waited.
class PendingDestinationScreen extends StatefulWidget {
  const PendingDestinationScreen({super.key, required this.city});

  final String city;

  @override
  State<PendingDestinationScreen> createState() => _PendingDestinationScreenState();
}

class _PendingDestinationScreenState extends State<PendingDestinationScreen> {
  final _loader = GlobalKey<LoaderState<_Rows>>();

  Future<void> _startTruck() async {
    final dispatched = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => LoadTruckScreen(stops: [widget.city])),
    );
    if (dispatched == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canDispatch = context.select<Session, bool>((s) => s.user?.canDispatch ?? false);
    return Scaffold(
      appBar: AppBar(title: Text('Pending for ${widget.city}')),
      bottomNavigationBar: canDispatch
          ? BottomBar(
              children: [BusyButton(icon: Icons.local_shipping_outlined, label: 'Plan a load', onPressed: _startTruck)],
            )
          : null,
      body: Loader<_Rows>(
        key: _loader,
        errorTitle: 'Could not load pending LRs',
        load: () async => (await context.read<ApiClient>().get('/pending/lrs', query: {'destination': widget.city})
                as List)
            .cast<Map<String, dynamic>>(),
        builder: (context, lrs) => lrs.isEmpty
            ? ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  MessageView(
                    card: true,
                    tone: Tone.success,
                    icon: Icons.check_rounded,
                    title: 'Nothing is waiting',
                    body: 'All goods for ${widget.city} have been dispatched.',
                  ),
                ],
              )
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                itemCount: lrs.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (_, i) => PendingLrCard(lr: lrs[i]),
              ),
      ),
    );
  }
}
