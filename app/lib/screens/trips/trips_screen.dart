import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/pdf_screen.dart';

StatusChip _statusChip(String status) => status == 'completed'
    ? const StatusChip('Delivered', background: Palette.successContainer, foreground: Palette.success)
    : const StatusChip('On road', background: Palette.primaryContainer, foreground: Palette.onPrimaryContainer);

/// Every truck sent out, newest first.
class TripsScreen extends StatefulWidget {
  const TripsScreen({super.key});

  @override
  State<TripsScreen> createState() => _TripsScreenState();
}

class _TripsScreenState extends State<TripsScreen> {
  final _loader = GlobalKey<LoaderState<List<Map<String, dynamic>>>>();

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Trips')),
      body: Loader<List<Map<String, dynamic>>>(
        key: _loader,
        errorTitle: 'Could not load trips',
        load: () async => (await context.read<ApiClient>().get('/trips') as List).cast<Map<String, dynamic>>(),
        builder: (context, trips) => trips.isEmpty
            ? ListView(
                children: const [
                  SizedBox(
                    height: 420,
                    child: MessageView(
                      icon: Icons.local_shipping_outlined,
                      title: 'No trips yet',
                      body: 'Start a truck from the Pending tab.',
                    ),
                  ),
                ],
              )
            : ListView.separated(
                padding: const EdgeInsets.all(16),
                itemCount: trips.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (_, i) {
                  final trip = trips[i];
                  final lines = trip['lines'] as List;
                  final delivered = lines.where((l) => l['delivered_at'] != null).length;
                  return AppCard(
                    child: ListTile(
                      minVerticalPadding: 16,
                      isThreeLine: true,
                      title: Text('${trip['vehicle_number']} → ${trip['destination']}', style: text.titleMedium),
                      subtitle: Text(
                        '$delivered of ${lines.length} LRs delivered\n'
                        'left ${dateTimeLabel(trip['dispatched_at'] as String)}',
                        style: text.bodyMedium,
                      ),
                      trailing: _statusChip(trip['status'] as String),
                      onTap: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute<void>(builder: (_) => TripDetailScreen(tripId: trip['id'] as String)),
                        );
                        await _loader.currentState?.reload();
                      },
                    ),
                  );
                },
              ),
      ),
    );
  }
}

/// One trip: what is on the truck, and a button to confirm each delivery.
class TripDetailScreen extends StatefulWidget {
  const TripDetailScreen({super.key, required this.tripId});

  final String tripId;

  @override
  State<TripDetailScreen> createState() => _TripDetailScreenState();
}

class _TripDetailScreenState extends State<TripDetailScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();
  String? _delivering;

  Future<void> _deliver(Map<String, dynamic> line) async {
    setState(() => _delivering = line['id'] as String);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/trips/${widget.tripId}/lines/${line['id']}/deliver', {});
      messenger.showSnackBar(SnackBar(content: Text('LR ${line['lr_number']} delivered.')));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
    if (!mounted) return;
    setState(() => _delivering = null);
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
    if (sure != true || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/trips/${widget.tripId}/lines/${line['id']}/undo-delivery', {});
      messenger.showSnackBar(SnackBar(content: Text('Delivery of ${line['lr_number']} undone.')));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
    await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canDispatch = context.select<Session, bool>((s) => s.user?.canDispatch ?? false);
    final canUndo = context.select<Session, bool>((s) => s.user?.canUndoDelivery ?? false);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trip'),
        actions: [
          TextButton.icon(
            icon: const Icon(Icons.picture_as_pdf_outlined),
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
        ],
      ),
      body: Loader<Map<String, dynamic>>(
        key: _loader,
        errorTitle: 'Could not load the trip',
        load: () async => await context.read<ApiClient>().get('/trips/${widget.tripId}') as Map<String, dynamic>,
        builder: (context, trip) {
          final lines = (trip['lines'] as List).cast<Map<String, dynamic>>();
          final driver = [trip['driver_name'], trip['driver_phone']].whereType<String>().join(' · ');
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              AppCard(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('${trip['vehicle_number']} → ${trip['destination']}', style: text.titleMedium),
                            const SizedBox(height: 4),
                            Text('left ${dateTimeLabel(trip['dispatched_at'] as String)}', style: text.bodyMedium),
                            if (driver.isNotEmpty) Text('Driver: $driver', style: text.bodyMedium),
                          ],
                        ),
                      ),
                      _statusChip(trip['status'] as String),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 24),
              Text('On this truck', style: text.titleMedium),
              const SizedBox(height: 12),
              for (final line in lines)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: AppCard(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('${line['lr_number']} · ${line['consignee_name']}', style: text.titleMedium),
                          const SizedBox(height: 4),
                          Text('${line['packages']} packages', style: text.bodyMedium),
                          const SizedBox(height: 12),
                          if (line['delivered_at'] != null)
                            Row(
                              children: [
                                Expanded(
                                  child: Align(
                                    alignment: Alignment.centerLeft,
                                    child: StatusChip(
                                      'Delivered ${dateTimeLabel(line['delivered_at'] as String)}',
                                      background: Palette.successContainer,
                                      foreground: Palette.success,
                                    ),
                                  ),
                                ),
                                if (canUndo) TextButton(onPressed: () => _undo(line), child: const Text('Undo')),
                              ],
                            )
                          else if (canDispatch)
                            OutlinedButton(
                              onPressed: _delivering == null ? () => _deliver(line) : null,
                              child: Text(_delivering == line['id'] ? 'Saving…' : 'Mark delivered'),
                            )
                          else
                            const StatusChip(
                              'On road',
                              background: Palette.primaryContainer,
                              foreground: Palette.onPrimaryContainer,
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
