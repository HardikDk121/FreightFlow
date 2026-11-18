import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../masterdata/master_data_screen.dart';
import '../masterdata/resource.dart';
import '../payments/payments_screens.dart';
import '../rates/rate_rule_form_screen.dart';
import '../team/users_screen.dart';
import '../trips/additions_screens.dart';
import '../trips/trips_screen.dart' show progressChip;

/// The rate matrix as tabs: rates, the stations they apply to, and the routes trucks run.
Widget rateMatrixScreen() => MasterDataScreen(
      title: 'Rate matrix',
      intro: 'Rates, the stations they apply to, and the routes trucks run.',
      resources: [rateRules, stations, routes],
    );

/// The owner's view: fleet, trips, freight booked, money owed, and what needs attention.
class AdminDashboardScreen extends StatefulWidget {
  const AdminDashboardScreen({super.key});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  void _open(BuildContext context, Widget screen) =>
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Owner dashboard')),
        body: Loader<Map<String, dynamic>>(
          key: _loader,
          errorTitle: 'Could not load the dashboard',
          load: () async => await context.read<ApiClient>().get('/dashboard/admin') as Map<String, dynamic>,
          builder: (context, d) {
            final text = Theme.of(context).textTheme;
            final muted = StatusColors.of(context).muted;
            final trucks = (d['trucks'] as List).cast<Map<String, dynamic>>();
            final days = (d['last_7_days'] as List).cast<Map<String, dynamic>>();
            final expiring = (d['eway_bills_expiring'] as List).cast<Map<String, dynamic>>();
            final debtors = (d['top_debtors'] as List).cast<Map<String, dynamic>>();
            final overdue = double.parse(d['receivables_overdue'] as String) > 0;
            final additions = (d['additions_waiting'] as List).cast<Map<String, dynamic>>();
            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (expiring.isNotEmpty) ...[
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(color: Palette.warningContainer, borderRadius: BorderRadius.circular(16)),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'E-way bills expiring within a day',
                          style: text.titleMedium!.copyWith(color: Palette.warning),
                        ),
                        for (final bill in expiring)
                          Text(
                            '${bill['lr_number']} on ${bill['vehicle_number'] ?? 'no truck'}: '
                            'until ${dateTimeLabel(bill['valid_until'] as String)}',
                            style: text.bodyMedium!.copyWith(color: Palette.warning),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                Row(
                  children: [
                    Expanded(child: _Figure('On road', '${d['trips_in_transit']}')),
                    const SizedBox(width: 12),
                    Expanded(child: _Figure('Part delivered', '${d['trips_partially_delivered']}')),
                    const SizedBox(width: 12),
                    Expanded(child: _Figure('Done today', '${d['trips_completed_today']}')),
                  ],
                ),
                if (additions.isNotEmpty) ...[
                  const SectionHeader('Cargo additions waiting', icon: Icons.add_box_outlined),
                  for (final challan in additions)
                    ChallanCard(challan: challan, showTruck: true, onChanged: () => _loader.currentState?.reload()),
                ],
                const SectionHeader('Freight booked', icon: Icons.trending_up),
                Row(
                  children: [
                    Expanded(child: _Figure('Today', 'Rs ${d['freight_today']}')),
                    const SizedBox(width: 12),
                    Expanded(child: _Figure('This month', 'Rs ${d['freight_this_month']}')),
                  ],
                ),
                const SizedBox(height: 12),
                AppCard(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Last 7 days', style: text.labelMedium),
                        const SizedBox(height: 12),
                        _Bars(days: days),
                      ],
                    ),
                  ),
                ),
                const SectionHeader('Money owed', icon: Icons.account_balance_wallet_outlined),
                AppCard(
                  child: InkWell(
                    onTap: () => _open(context, const ReceivablesScreen()),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('Rs ${d['receivables_outstanding']}', style: text.headlineMedium),
                                Text(
                                  'Rs ${d['receivables_overdue']} overdue',
                                  style: text.bodyMedium!.copyWith(color: overdue ? Palette.error : muted),
                                ),
                                for (final p in debtors)
                                  Text('${p['party']}: Rs ${p['outstanding']}', style: text.bodyMedium),
                              ],
                            ),
                          ),
                          const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
                        ],
                      ),
                    ),
                  ),
                ),
                const SectionHeader('Trucks', icon: Icons.local_shipping_outlined),
                if (trucks.isEmpty) Text('No trucks yet.', style: text.bodyMedium),
                for (final truck in trucks)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: AppCard(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(truck['vehicle_number'] as String, style: text.titleMedium),
                                  const SizedBox(height: 4),
                                  Text(
                                    truck['state'] == 'on_trip'
                                        ? 'Heading to ${truck['next_stop']}'
                                            '${truck['next_stop'] == truck['destination'] ? '' : ', then on to ${truck['destination']}'}'
                                        : 'Free at ${truck['location'] ?? 'an unrecorded place'}',
                                    style: text.bodyMedium,
                                  ),
                                  if (truck['papers_expired'] as bool)
                                    Text(
                                      'Insurance or fitness has expired',
                                      style: text.bodyMedium!.copyWith(color: Palette.error),
                                    ),
                                ],
                              ),
                            ),
                            truck['state'] == 'on_trip'
                                ? progressChip(truck['progress'] as String)
                                : const StatusChip(
                                    'Free',
                                    background: Palette.successContainer,
                                    foreground: Palette.success,
                                  ),
                          ],
                        ),
                      ),
                    ),
                  ),
                const SectionHeader('This month', icon: Icons.leaderboard_outlined),
                _Ranking(title: 'Top destinations', rows: (d['top_destinations'] as List).cast<Map<String, dynamic>>()),
                const SizedBox(height: 12),
                _Ranking(title: 'Top clients', rows: (d['top_clients'] as List).cast<Map<String, dynamic>>()),
                const SectionHeader('Manage', icon: Icons.tune),
                OutlinedButton(onPressed: () => _open(context, rateMatrixScreen()), child: const Text('Rate matrix')),
                const SizedBox(height: 8),
                OutlinedButton(onPressed: () => _open(context, const UsersScreen()), child: const Text('Team')),
              ],
            );
          },
        ),
      );
}

class _Figure extends StatelessWidget {
  const _Figure(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(value, style: text.titleLarge)),
            const SizedBox(height: 2),
            Text(label, style: text.bodySmall!.copyWith(color: StatusColors.of(context).muted)),
          ],
        ),
      ),
    );
  }
}

/// Seven bars, one per day, scaled to the best day.
class _Bars extends StatelessWidget {
  const _Bars({required this.days});

  final List<Map<String, dynamic>> days;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final amounts = [for (final day in days) double.parse(day['freight'] as String)];
    final best = amounts.fold<double>(0, (a, b) => b > a ? b : a);
    return SizedBox(
      height: 120,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (var i = 0; i < days.length; i++)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    Container(
                      height: best == 0 ? 2 : 2 + 88 * amounts[i] / best,
                      decoration: BoxDecoration(
                        color: i == days.length - 1 ? Palette.primary : Palette.primaryContainer,
                        borderRadius: BorderRadius.circular(6),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text((days[i]['date'] as String).substring(8), style: text.bodySmall),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _Ranking extends StatelessWidget {
  const _Ranking({required this.title, required this.rows});

  final String title;
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: text.labelMedium),
            const SizedBox(height: 8),
            if (rows.isEmpty) Text('Nothing booked this month yet.', style: text.bodyMedium),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    Expanded(child: Text(row['name'] as String, style: text.bodyMedium)),
                    Text('Rs ${row['freight']}', style: text.bodyMedium),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
