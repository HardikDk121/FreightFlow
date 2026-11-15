import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../home/home_screen.dart' show DestinationCard;
import 'load_truck_screen.dart';

/// Every destination with goods waiting, the longest-waiting first.
class PendingScreen extends StatefulWidget {
  const PendingScreen({super.key});

  @override
  State<PendingScreen> createState() => _PendingScreenState();
}

class _PendingScreenState extends State<PendingScreen> {
  final _loader = GlobalKey<LoaderState<List<Map<String, dynamic>>>>();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Pending goods')),
        body: Loader<List<Map<String, dynamic>>>(
          key: _loader,
          errorTitle: 'Could not load pending goods',
          load: () async => (await context.read<ApiClient>().get('/pending') as List).cast<Map<String, dynamic>>(),
          builder: (context, destinations) => destinations.isEmpty
              ? ListView(
                  children: const [
                    SizedBox(
                      height: 420,
                      child: MessageView(
                        icon: Icons.check_circle_outline,
                        title: 'Nothing is waiting',
                        body: 'Every booked LR has been dispatched.',
                      ),
                    ),
                  ],
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: destinations.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (_, i) => DestinationCard(
                    destination: destinations[i],
                    onReturn: () => _loader.currentState?.reload(),
                  ),
                ),
        ),
      );
}

/// The LRs waiting for one destination, oldest first, with how long each has waited.
class PendingDestinationScreen extends StatefulWidget {
  const PendingDestinationScreen({super.key, required this.city});

  final String city;

  @override
  State<PendingDestinationScreen> createState() => _PendingDestinationScreenState();
}

class _PendingDestinationScreenState extends State<PendingDestinationScreen> {
  final _loader = GlobalKey<LoaderState<List<Map<String, dynamic>>>>();

  Future<void> _startTruck() async {
    final dispatched = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => LoadTruckScreen(city: widget.city)),
    );
    if (dispatched == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canDispatch = context.select<Session, bool>((s) => s.user?.canDispatch ?? false);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text('Pending for ${widget.city}')),
      floatingActionButton: canDispatch
          ? FloatingActionButton.extended(
              heroTag: 'start-truck',
              onPressed: _startTruck,
              icon: const Icon(Icons.local_shipping_outlined),
              label: const Text('Start a truck'),
            )
          : null,
      body: Loader<List<Map<String, dynamic>>>(
        key: _loader,
        errorTitle: 'Could not load pending LRs',
        load: () async => (await context.read<ApiClient>().get('/pending/lrs', query: {'destination': widget.city})
                as List)
            .cast<Map<String, dynamic>>(),
        builder: (context, lrs) => lrs.isEmpty
            ? ListView(
                children: [
                  SizedBox(
                    height: 420,
                    child: MessageView(
                      icon: Icons.check_circle_outline,
                      title: 'Nothing is waiting',
                      body: 'All goods for ${widget.city} have been dispatched.',
                    ),
                  ),
                ],
              )
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                itemCount: lrs.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (_, i) {
                  final lr = lrs[i];
                  final days = lr['days_waiting'] as int;
                  final late = days > 3;
                  return AppCard(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text(lr['lr_number'] as String, style: text.titleMedium)),
                              StatusChip(
                                waitingLabel(days),
                                background: late ? Palette.warningContainer : Palette.primaryContainer,
                                foreground: late ? Palette.warning : Palette.onPrimaryContainer,
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Text('${lr['consignor_name']} → ${lr['consignee_name']}', style: text.bodyMedium),
                          const SizedBox(height: 4),
                          Text(
                            '${lr['pending']} of ${lr['packages']} packages waiting · ${lr['goods_description']}',
                            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
      ),
    );
  }
}
