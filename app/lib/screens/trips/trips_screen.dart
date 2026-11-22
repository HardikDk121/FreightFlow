import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/pdf_screen.dart';
import '../hire/hire_screens.dart' show TripMoneyScreen;
import '../shell.dart';
import 'additions_screens.dart';

/// in_transit, partially_delivered or delivered, as a labelled pill.
StatusChip progressChip(String progress) => switch (progress) {
      'delivered' => StatusChip.tone('Delivered', Tone.success),
      'partially_delivered' => StatusChip.tone('Part delivered', Tone.warning),
      _ => StatusChip.tone('On road', Tone.info),
    };

String _route(Map<String, dynamic> trip) => [for (final s in (trip['stops'] as List)) s['city'] as String].join(' → ');

typedef _Rows = List<Map<String, dynamic>>;

/// Every truck sent out, newest first, filtered by whether it is still on the road.
class TripsScreen extends StatefulWidget {
  const TripsScreen({super.key});

  @override
  State<TripsScreen> createState() => _TripsScreenState();
}

class _TripsScreenState extends State<TripsScreen> {
  final _loader = GlobalKey<LoaderState<(_Rows, _Rows)>>();

  /// all, dispatched (on the road) or completed.
  String _filter = 'all';

  /// The trips, and any cargo additions still waiting for approval or for the driver.
  Future<(_Rows, _Rows)> _load() async {
    final api = context.read<ApiClient>();
    final trips = (await api.get('/trips') as List).cast<Map<String, dynamic>>();
    final waiting = (await api.get('/challans/open') as List).cast<Map<String, dynamic>>();
    return (trips, waiting);
  }

  Future<void> _open(Map<String, dynamic> trip) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => TripDetailScreen(tripId: trip['id'] as String)),
    );
    await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Trips')),
        body: Loader<(_Rows, _Rows)>(
          key: _loader,
          errorTitle: 'Could not load trips',
          load: _load,
          builder: (context, data) {
            final (trips, waiting) = data;
            final onRoad = trips.where((t) => t['status'] == 'dispatched').length;
            final shown = _filter == 'all' ? trips : trips.where((t) => t['status'] == _filter).toList();
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, navBarClearance),
              children: [
                Segmented<String>(
                  options: {
                    'all': 'All trips',
                    'dispatched': 'On road · $onRoad',
                    'completed': 'Delivered',
                  },
                  value: _filter,
                  onChanged: (f) => setState(() => _filter = f),
                ),
                const SizedBox(height: 16),
                if (waiting.isNotEmpty) ...[
                  const SectionHeader('Cargo additions waiting', icon: Icons.add_box_outlined),
                  for (final challan in waiting)
                    ChallanCard(challan: challan, showTruck: true, onChanged: () => _loader.currentState?.reload()),
                  const SizedBox(height: 8),
                ],
                if (shown.isEmpty)
                  MessageView(
                    card: true,
                    icon: Icons.local_shipping_outlined,
                    title: trips.isEmpty ? 'No trips yet' : 'No trips here',
                    body: trips.isEmpty ? 'Plan a load from the Pending tab.' : 'Try another filter.',
                    actionLabel: trips.isEmpty ? 'Go to Pending' : null,
                    onAction: () => ShellScope.of(context)?.goTo(ShellTab.pending),
                  ),
                for (final trip in shown) ...[TripCard(trip: trip, onTap: () => _open(trip)), const SizedBox(height: 12)],
              ],
            );
          },
        ),
      );
}

/// One trip in a list: truck, route, how much is delivered, when it left.
class TripCard extends StatelessWidget {
  const TripCard({super.key, required this.trip, required this.onTap});

  final Map<String, dynamic> trip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final lines = trip['lines'] as List;
    final delivered = lines.where((l) => l['delivered_at'] != null).length;
    final next = trip['next_stop'] as String?;
    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.local_shipping_outlined, size: 22, color: Palette.onSurface),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  '${trip['vehicle_number']} → ${trip['destination']}',
                  style: text.titleMedium,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if ((trip['stops'] as List).length > 1) Text(_route(trip), style: text.labelMedium),
          Text(
            '$delivered of ${lines.length} LRs delivered${next == null ? '' : ' · next stop $next'}',
            style: text.bodyMedium,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: Text(
                  'Left ${dateTimeLabel(trip['dispatched_at'] as String)}',
                  style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                ),
              ),
              progressChip(trip['progress'] as String),
            ],
          ),
        ],
      ),
    );
  }
}

/// One trip, stop by stop: what is on the truck for each station, with delivery per stop or per LR.
class TripDetailScreen extends StatefulWidget {
  const TripDetailScreen({super.key, required this.tripId});

  final String tripId;

  @override
  State<TripDetailScreen> createState() => _TripDetailScreenState();
}

class _TripDetailScreenState extends State<TripDetailScreen> {
  final _loader = GlobalKey<LoaderState<(Map<String, dynamic>, _Rows)>>();
  bool _saving = false;

  /// The trip and its challans: the primary one, and one for each time cargo was added on the road.
  Future<(Map<String, dynamic>, _Rows)> _load() async {
    final api = context.read<ApiClient>();
    final trip = await api.get('/trips/${widget.tripId}') as Map<String, dynamic>;
    final challans = (await api.get('/trips/${widget.tripId}/challans') as List).cast<Map<String, dynamic>>();
    return (trip, challans);
  }

  Future<void> _addCargo(Map<String, dynamic> trip) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => AddCargoScreen(trip: trip)));
    await _loader.currentState?.reload();
  }

  /// Run one delivery action, show what happened, and reload the trip.
  Future<void> _act(String path, String done) async {
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/trips/${widget.tripId}/$path', {});
      messenger.showSnackBar(SnackBar(content: Text(done)));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
    if (!mounted) return;
    setState(() => _saving = false);
    await _loader.currentState?.reload();
  }

  /// Take back a delivery marked by mistake, after asking once.
  Future<void> _undo(Map<String, dynamic> line) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text('Undo delivery of ${line['lr_number']}?'),
        content: const Text('The LR goes back to "on road". This is recorded with your name.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialog).pop(false), child: const Text('Keep it')),
          TextButton(onPressed: () => Navigator.of(dialog).pop(true), child: const Text('Undo delivery')),
        ],
      ),
    );
    if (sure == true && mounted) {
      await _act('lines/${line['id']}/undo-delivery', 'Delivery of ${line['lr_number']} undone.');
    }
  }

  /// One LR on the truck, with its delivery actions side by side.
  Widget _line(Map<String, dynamic> line, bool canDispatch, bool canUndo) {
    final text = Theme.of(context).textTheme;
    final delivered = line['delivered_at'] as String?;
    final added = (line['challan_number'] as String).contains('/S');
    final compact = OutlinedButton.styleFrom(minimumSize: const Size(0, 42), padding: const EdgeInsets.symmetric(horizontal: 12));
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: Palette.background, borderRadius: BorderRadius.circular(16)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${line['lr_number']} · ${line['consignee_name']}', style: text.labelLarge),
          const SizedBox(height: 2),
          Text(
            '${line['packages']} packages · ${line['challan_number']}${added ? ', added at ${line['loaded_at']}' : ''}',
            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              delivered != null
                  ? StatusChip.tone('Delivered ${dateTimeLabel(delivered)}', Tone.success)
                  : StatusChip.tone('On road', Tone.info),
              const Spacer(),
              if (canUndo && delivered != null)
                Text('ADMIN', style: text.labelSmall!.copyWith(color: Palette.error)),
            ],
          ),
          if ((canDispatch && delivered == null) || (canUndo && delivered != null)) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(minimumSize: const Size(0, 42)),
                    onPressed: canDispatch && delivered == null && !_saving
                        ? () => _act('lines/${line['id']}/deliver', 'LR ${line['lr_number']} delivered.')
                        : null,
                    child: const Text('Mark delivered'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton(
                    style: compact,
                    onPressed: canUndo && delivered != null && !_saving ? () => _undo(line) : null,
                    child: const Text('Undo delivery'),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  /// The route as a vertical line of stops, each with its count and an "all delivered" action.
  Widget _stop(Map<String, dynamic> stop, bool isLast, bool canDispatch, List<Widget> lines) {
    final text = Theme.of(context).textTheme;
    final done = (stop['delivered_count'] as int) >= (stop['lr_count'] as int);
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                Container(
                  width: 22,
                  height: 22,
                  margin: const EdgeInsets.only(top: 2),
                  decoration: BoxDecoration(
                    color: done ? Palette.success : Palette.primary,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(done ? Icons.check : Icons.circle, size: done ? 14 : 8, color: done ? Palette.onInk : Palette.onPrimary),
                ),
                if (!isLast) Expanded(child: Container(width: 2, color: Palette.outline)),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(stop['city'] as String, style: text.titleMedium),
                            Text(
                              '${stop['delivered_count']} of ${stop['lr_count']} delivered',
                              style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                            ),
                          ],
                        ),
                      ),
                      if (canDispatch && !done)
                        TextButton(
                          onPressed: _saving
                              ? null
                              : () => _act(
                                    'stops/${Uri.encodeComponent(stop['city'] as String)}/deliver',
                                    'Everything for ${stop['city']} delivered.',
                                  ),
                          child: const Text('All delivered'),
                        ),
                    ],
                  ),
                  if (stop['lr_count'] == 0)
                    Text('Nothing to drop here on this trip.', style: text.bodySmall)
                  else ...[
                    const SizedBox(height: 8),
                    ...lines,
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final canDispatch = context.select<Session, bool>((s) => s.user?.canDispatch ?? false);
    final canUndo = context.select<Session, bool>((s) => s.user?.canUndoDelivery ?? false);
    final seesHire = context.select<Session, bool>((s) => s.user?.can('vendors.manage') ?? false);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trip'),
        actions: [
          if (seesHire)
            IconButton(
              tooltip: 'Hire and profit',
              icon: const Icon(Icons.currency_rupee),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => TripMoneyScreen(tripId: widget.tripId, title: 'Hire and profit')),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size(0, 40), padding: const EdgeInsets.symmetric(horizontal: 14)),
              icon: const Icon(Icons.picture_as_pdf_outlined, size: 18),
              label: const Text('Load sheet'),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => PdfScreen(
                    title: 'Load sheet',
                    path: '/trips/${widget.tripId}/load-sheet.pdf',
                    fileName: 'load-sheet-${widget.tripId}.pdf',
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      body: Loader<(Map<String, dynamic>, _Rows)>(
        key: _loader,
        errorTitle: 'Could not load the trip',
        load: _load,
        builder: (context, data) {
          final (trip, challans) = data;
          final lines = (trip['lines'] as List).cast<Map<String, dynamic>>();
          final stops = (trip['stops'] as List).cast<Map<String, dynamic>>();
          final driver = [trip['driver_name'], trip['driver_phone']].whereType<String>().join(' · ');
          final next = trip['next_stop'] as String?;
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
            children: [
              DarkPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(trip['vehicle_number'] as String, style: onInk(text.titleLarge!))),
                        progressChip(trip['progress'] as String),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(_route(trip), style: text.titleMedium!.copyWith(color: Palette.primary)),
                    const SizedBox(height: 6),
                    Text(
                      next == null
                          ? 'All goods delivered. The truck is free at ${trip['destination']}.'
                          : 'Next stop $next. The truck is busy until the last stop is delivered.',
                      style: onInk(text.bodyMedium!, muted: true),
                    ),
                    Text('Left ${dateTimeLabel(trip['dispatched_at'] as String)}', style: onInk(text.bodySmall!, muted: true)),
                    if (driver.isNotEmpty) Text('Driver: $driver', style: onInk(text.bodySmall!, muted: true)),
                    if (trip['status'] == 'dispatched') ...[
                      const SizedBox(height: 14),
                      OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Palette.onInk,
                          side: const BorderSide(color: Palette.onInkMuted),
                          minimumSize: const Size.fromHeight(46),
                        ),
                        onPressed: () => _addCargo(trip),
                        icon: const Icon(Icons.add_box_outlined),
                        label: const Text('Add cargo on the road'),
                      ),
                    ],
                  ],
                ),
              ),
              const SectionHeader('Delivery', icon: Icons.route_outlined),
              AppCard(
                padding: const EdgeInsets.fromLTRB(14, 18, 14, 0),
                child: Column(
                  children: [
                    for (var i = 0; i < stops.length; i++)
                      _stop(
                        stops[i],
                        i == stops.length - 1,
                        canDispatch,
                        [for (final line in lines.where((l) => l['to_city'] == stops[i]['city'])) _line(line, canDispatch, canUndo)],
                      ),
                  ],
                ),
              ),
              if (canUndo)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Delivered receipts can be reopened by an admin or manager.',
                    style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                  ),
                ),
              const SectionHeader('Challans', icon: Icons.description_outlined),
              for (final challan in challans) ChallanCard(challan: challan, onChanged: () => _loader.currentState?.reload()),
            ],
          );
        },
      ),
    );
  }
}
