import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../account/account_screen.dart';
import '../pending/pending_screen.dart';

/// Today at a glance: what was booked, what is waiting, what is on the road.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('FreightFlow'),
          actions: [
            IconButton(
              tooltip: 'Account and settings',
              icon: const Icon(Icons.account_circle_outlined),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const AccountScreen()),
              ),
            ),
          ],
        ),
        body: Loader<Map<String, dynamic>>(
          errorTitle: 'Could not load the dashboard',
          load: () async => await context.read<ApiClient>().get('/dashboard') as Map<String, dynamic>,
          builder: (context, board) {
            final text = Theme.of(context).textTheme;
            final destinations = (board['pending_by_destination'] as List).cast<Map<String, dynamic>>();
            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Row(
                  children: [
                    Expanded(child: _Stat(label: 'LRs today', value: board['lrs_today'] as int)),
                    const SizedBox(width: 12),
                    Expanded(child: _Stat(label: 'Trucks on road', value: board['trips_on_road'] as int)),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(child: _Stat(label: 'Pending packages', value: board['pending_packages'] as int)),
                    const SizedBox(width: 12),
                    Expanded(child: _Stat(label: 'Pending LRs', value: board['pending_lrs'] as int)),
                  ],
                ),
                const SizedBox(height: 24),
                Text('Waiting by destination', style: text.titleMedium),
                const SizedBox(height: 12),
                if (destinations.isEmpty)
                  Text('Nothing is waiting in the godown.', style: text.bodyMedium)
                else
                  for (final d in destinations) ...[DestinationCard(destination: d), const SizedBox(height: 12)],
              ],
            );
          },
        ),
      );
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});

  final String label;
  final int value;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$value', style: text.headlineMedium),
            const SizedBox(height: 4),
            Text(label, style: text.bodyMedium!.copyWith(color: StatusColors.of(context).muted)),
          ],
        ),
      ),
    );
  }
}

/// One destination with goods waiting. Opens its pending list. Shared by Home and the Pending tab.
class DestinationCard extends StatelessWidget {
  const DestinationCard({super.key, required this.destination, this.onReturn});

  final Map<String, dynamic> destination;

  /// Called when the person comes back from the destination's screen, to refresh the list.
  final VoidCallback? onReturn;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final days = destination['days_waiting'] as int;
    final count = destination['lr_count'] as int;
    final late = days > 3;
    return AppCard(
      child: ListTile(
        minVerticalPadding: 16,
        title: Text(destination['to_city'] as String, style: text.titleMedium),
        subtitle: Text(
          '${destination['packages']} packages on $count LR${count == 1 ? '' : 's'}',
          style: text.bodyMedium,
        ),
        trailing: StatusChip(
          'oldest ${waitingLabel(days)}',
          background: late ? Palette.warningContainer : Palette.primaryContainer,
          foreground: late ? Palette.warning : Palette.onPrimaryContainer,
        ),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => PendingDestinationScreen(city: destination['to_city'] as String),
            ),
          );
          onReturn?.call();
        },
      ),
    );
  }
}
