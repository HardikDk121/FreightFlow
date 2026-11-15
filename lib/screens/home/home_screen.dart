import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../account/account_screen.dart';
import '../lr/lr_form_screen.dart';
import '../pending/pending_screen.dart';

const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// Today at a glance: a greeting, the main action, the day's numbers, and what is waiting.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Future<void> _open(Widget screen) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
    await _loader.currentState?.reload();
  }

  static String _greeting(int hour) => hour < 12
      ? 'Good morning'
      : hour < 17
          ? 'Good afternoon'
          : 'Good evening';

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user;
    final text = Theme.of(context).textTheme;
    final muted = StatusColors.of(context).muted;
    final now = DateTime.now();
    return Scaffold(
      appBar: AppBar(
        title: const Text('FreightFlow'),
        actions: [
          IconButton(
            tooltip: 'Account and settings',
            icon: const Icon(Icons.account_circle_outlined),
            onPressed: () => _open(const AccountScreen()),
          ),
        ],
      ),
      body: Loader<Map<String, dynamic>>(
        key: _loader,
        errorTitle: 'Could not load the dashboard',
        load: () async => await context.read<ApiClient>().get('/dashboard') as Map<String, dynamic>,
        builder: (context, board) {
          final destinations = (board['pending_by_destination'] as List).cast<Map<String, dynamic>>();
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('${_greeting(now.hour)}, ${user?.name.split(' ').first ?? ''}', style: text.headlineMedium),
              const SizedBox(height: 4),
              Text(
                '${_weekdays[now.weekday - 1]}, ${now.day} ${_months[now.month - 1]} ${now.year}',
                style: text.bodyMedium!.copyWith(color: muted),
              ),
              const SizedBox(height: 20),
              if (user?.canBookLr ?? false) ...[
                _ActionCard(onTap: () => _open(const LrFormScreen())),
                const SizedBox(height: 20),
              ],
              Row(
                children: [
                  Expanded(
                    child: _Stat(
                      icon: Icons.receipt_long_outlined,
                      label: 'LRs booked today',
                      value: board['lrs_today'] as int,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _Stat(
                      icon: Icons.local_shipping_outlined,
                      label: 'Trucks on the road',
                      value: board['trips_on_road'] as int,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _Stat(
                      icon: Icons.inventory_2_outlined,
                      label: 'Packages waiting',
                      value: board['pending_packages'] as int,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _Stat(
                      icon: Icons.pending_actions_outlined,
                      label: 'LRs waiting',
                      value: board['pending_lrs'] as int,
                    ),
                  ),
                ],
              ),
              const SectionHeader('Waiting by destination', icon: Icons.place_outlined),
              if (destinations.isEmpty)
                AppCard(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text('Nothing is waiting in the godown.', style: text.bodyMedium),
                  ),
                )
              else
                for (final d in destinations) ...[
                  DestinationCard(destination: d, onReturn: () => _loader.currentState?.reload()),
                  const SizedBox(height: 12),
                ],
            ],
          );
        },
      ),
    );
  }
}

/// The main thing to do from Home: book an LR.
class _ActionCard extends StatelessWidget {
  const _ActionCard({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Material(
      color: Palette.primary,
      borderRadius: BorderRadius.circular(20),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(color: const Color(0x33FFFFFF), borderRadius: BorderRadius.circular(14)),
                child: const Icon(Icons.document_scanner_outlined, color: Palette.onPrimary),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Book a new LR', style: text.titleLarge!.copyWith(color: Palette.onPrimary)),
                    const SizedBox(height: 2),
                    Text(
                      'Scan the invoice or type it in.',
                      style: text.bodyMedium!.copyWith(color: Palette.onPrimary),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward, color: Palette.onPrimary),
            ],
          ),
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.icon, required this.label, required this.value});

  final IconData icon;
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
            Icon(icon, color: Palette.primary),
            const SizedBox(height: 12),
            Text('$value', style: text.headlineMedium),
            const SizedBox(height: 2),
            Text(label, style: text.bodyMedium!.copyWith(color: StatusColors.of(context).muted)),
          ],
        ),
      ),
    );
  }
}

/// One destination with goods waiting. Opens its pending list. Shared by Home and the Pending tab.
class DestinationCard extends StatelessWidget {
  const DestinationCard({super.key, required this.destination, required this.onReturn});

  final Map<String, dynamic> destination;

  /// Called when the person comes back from the destination's screen, to refresh the list.
  final VoidCallback onReturn;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final days = destination['days_waiting'] as int;
    final count = destination['lr_count'] as int;
    final late = days > 3;
    return AppCard(
      child: InkWell(
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => PendingDestinationScreen(city: destination['to_city'] as String),
            ),
          );
          onReturn();
        },
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(destination['to_city'] as String, style: text.titleMedium),
                    const SizedBox(height: 4),
                    Text(
                      '${destination['packages']} packages on $count LR${count == 1 ? '' : 's'}',
                      style: text.bodyMedium,
                    ),
                    const SizedBox(height: 10),
                    StatusChip(
                      'Oldest ${waitingLabel(days)}',
                      background: late ? Palette.warningContainer : Palette.primaryContainer,
                      foreground: late ? Palette.warning : Palette.onPrimaryContainer,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
            ],
          ),
        ),
      ),
    );
  }
}
