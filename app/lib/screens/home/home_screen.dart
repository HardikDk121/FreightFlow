import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../account/account_screen.dart';
import '../admin/admin_dashboard_screen.dart';
import '../lr/lr_form_screen.dart';
import '../pending/pending_screen.dart';
import '../shell.dart';

const _weekdays = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'];
const _months = [
  'JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE',
  'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER',
];

/// Today at a glance: a greeting, the four things people do most, the day's numbers, and what is waiting.
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
    final now = DateTime.now();
    final shell = ShellScope.of(context);
    return Scaffold(
      body: Column(
        children: [
          HeroHeader(
            leading: const Wordmark(),
            trailing: IconButton(
              tooltip: 'Account and settings',
              icon: const Icon(Icons.person_outline, color: Palette.onInk),
              onPressed: () => _open(const AccountScreen()),
            ),
            title: '${_greeting(now.hour)}, ${user?.name.split(' ').first ?? ''}',
            subtitle: '${_weekdays[now.weekday - 1]}, ${now.day} ${_months[now.month - 1]} ${now.year}',
          ),
          Expanded(
            child: Loader<Map<String, dynamic>>(
              key: _loader,
              errorTitle: 'Could not load today',
              load: () async => await context.read<ApiClient>().get('/dashboard') as Map<String, dynamic>,
              builder: (context, board) {
                final destinations = (board['pending_by_destination'] as List).cast<Map<String, dynamic>>();
                final waiting = board['pending_packages'] as int;
                final onRoad = board['trips_on_road'] as int;
                final canBook = user?.canBookLr ?? false;
                return ListView(
                  padding: const EdgeInsets.fromLTRB(20, 20, 20, navBarClearance),
                  children: [
                    _ActionGrid(
                      tiles: [
                        if (canBook)
                          _Tile(
                            icon: Icons.north_east,
                            title: 'New LR',
                            subtitle: 'Create a receipt',
                            dark: true,
                            onTap: () => _open(const LrFormScreen()),
                          ),
                        if (canBook)
                          _Tile(
                            icon: Icons.document_scanner_outlined,
                            title: 'Scan invoice',
                            subtitle: 'Let the camera do it',
                            onTap: () => _open(const LrFormScreen(startWithScan: true)),
                          ),
                        _Tile(
                          icon: Icons.inventory_2_outlined,
                          title: 'Pending goods',
                          subtitle: waiting == 0 ? 'All clear today' : '$waiting packages waiting',
                          onTap: () => shell?.goTo(ShellTab.pending),
                        ),
                        _Tile(
                          icon: Icons.local_shipping_outlined,
                          title: 'Trips',
                          subtitle: onRoad == 0 ? 'No truck on the road' : '$onRoad on the road',
                          onTap: () => shell?.goTo(ShellTab.trips),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    DarkPanel(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const SectionLabel('Today', onDark: true),
                          Row(
                            children: [
                              Expanded(child: MetricTile(value: '${board['lrs_today']}', label: 'LRs booked', onDark: true)),
                              Expanded(child: MetricTile(value: '$onRoad', label: 'Trucks on the road', onDark: true)),
                            ],
                          ),
                          const SizedBox(height: 16),
                          Row(
                            children: [
                              Expanded(child: MetricTile(value: '$waiting', label: 'Packages waiting', onDark: true)),
                              Expanded(
                                child: MetricTile(value: '${board['pending_lrs']}', label: 'LRs waiting', onDark: true),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    if (user?.isAdmin ?? false) ...[
                      const SizedBox(height: 12),
                      AppCard(
                        onTap: () => _open(const AdminDashboardScreen()),
                        child: const ListTile(
                          contentPadding: EdgeInsets.symmetric(horizontal: 18, vertical: 6),
                          leading: Icon(Icons.insights_outlined, color: Palette.onSurface),
                          title: Text('Owner dashboard'),
                          subtitle: Text('Revenue, money owed, fleet and rates'),
                          trailing: Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
                        ),
                      ),
                    ],
                    const SectionHeader('Waiting by destination', icon: Icons.place_outlined),
                    if (destinations.isEmpty)
                      AppCard(
                        padding: const EdgeInsets.all(18),
                        child: Row(
                          children: [
                            Container(
                              width: 40,
                              height: 40,
                              decoration: const BoxDecoration(color: Palette.successContainer, shape: BoxShape.circle),
                              child: const Icon(Icons.check, color: Palette.success),
                            ),
                            const SizedBox(width: 14),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text('Nothing is waiting', style: Theme.of(context).textTheme.titleMedium),
                                  Text(
                                    'Every booked LR is on its way.',
                                    style: Theme.of(context).textTheme.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
                                  ),
                                ],
                              ),
                            ),
                          ],
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
          ),
        ],
      ),
    );
  }
}

class _Tile {
  const _Tile({required this.icon, required this.title, required this.subtitle, required this.onTap, this.dark = false});

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool dark;
}

/// Quick actions, two to a row.
class _ActionGrid extends StatelessWidget {
  const _ActionGrid({required this.tiles});

  final List<_Tile> tiles;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    Widget tile(_Tile t) => AppCard(
          color: t.dark ? Palette.ink : Palette.surface,
          onTap: t.onTap,
          padding: const EdgeInsets.all(16),
          child: SizedBox(
            height: 92,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(t.icon, size: 26, color: t.dark ? Palette.primary : Palette.onSurface),
                const Spacer(),
                Text(t.title, style: t.dark ? onInk(text.titleMedium!) : text.titleMedium),
                Text(
                  t.subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: t.dark ? onInk(text.bodySmall!, muted: true) : text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                ),
              ],
            ),
          ),
        );
    return Column(
      children: [
        for (var i = 0; i < tiles.length; i += 2) ...[
          if (i > 0) const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: tile(tiles[i])),
              const SizedBox(width: 12),
              Expanded(child: i + 1 < tiles.length ? tile(tiles[i + 1]) : const SizedBox.shrink()),
            ],
          ),
        ],
      ],
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
    final weight = double.parse(destination['weight_kg'] as String);
    return AppCard(
      padding: const EdgeInsets.all(18),
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => PendingDestinationScreen(city: destination['to_city'] as String)),
        );
        onReturn();
      },
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(destination['to_city'] as String, style: text.titleMedium),
                const SizedBox(height: 4),
                Text(
                  '${destination['packages']} pkgs · ${kgLabel(weight)} · $count LR${count == 1 ? '' : 's'}',
                  style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
                ),
                const SizedBox(height: 10),
                StatusChip.tone('Oldest ${waitingLabel(days)}', days > 3 ? Tone.warning : Tone.info),
              ],
            ),
          ),
          const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
        ],
      ),
    );
  }
}
