import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';

/// "Due on delivery", "Due 04-10-2026", "Overdue since 04-10-2026".
String dueLabel(Map<String, dynamic> account) {
  final due = account['due_on'] as String?;
  if (due == null) return 'Due on delivery';
  return account['overdue'] as bool ? 'Overdue since ${dayLabel(due)}' : 'Due ${dayLabel(due)}';
}

const methodLabels = {'cash': 'Cash', 'upi': 'UPI', 'cheque': 'Cheque', 'bank_transfer': 'Bank transfer'};

/// A collection's bank status as a pill: whether the money has been seen in the company account.
StatusChip collectionStatusChip(String status) => switch (status) {
      'confirmed' => StatusChip.tone('In the bank', Tone.success),
      'failed' => StatusChip.tone('Failed', Tone.danger),
      'legacy' => StatusChip.tone('Recorded before checks', Tone.neutral),
      _ => StatusChip.tone('Not yet in the bank', Tone.warning),
    };

/// What one LR is owed and every collection set against it. Money is recorded through a money
/// receipt (Collections), never here, so each payment has a receipt, a collector and a bank check.
class LrAccountScreen extends StatelessWidget {
  const LrAccountScreen({super.key, required this.lrId, required this.lrNumber});

  final String lrId;
  final String lrNumber;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text('Payments · $lrNumber')),
      body: Loader<Map<String, dynamic>>(
        errorTitle: 'Could not load the payments',
        load: () async => await context.read<ApiClient>().get('/lrs/$lrId/account') as Map<String, dynamic>,
        builder: (context, account) {
          final payments = (account['payments'] as List).cast<Map<String, dynamic>>();
          final settled = double.parse(account['balance'] as String) <= 0;
          final overdue = account['overdue'] as bool;
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
            children: [
              DarkPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionLabel('Balance', onDark: true),
                    Text(money(account['balance'] as String), style: onInk(text.headlineMedium!)),
                    const SizedBox(height: 6),
                    Text(
                      'Total ${money(account['total'] as String)} · received ${money(account['paid'] as String)}',
                      style: onInk(text.bodyMedium!, muted: true),
                    ),
                    Text('${account['payer']} pays (${account['freight_by']})', style: onInk(text.bodyMedium!, muted: true)),
                    const SizedBox(height: 12),
                    settled
                        ? StatusChip.tone('Settled', Tone.success)
                        : StatusChip.tone(dueLabel(account), overdue ? Tone.danger : Tone.info),
                  ],
                ),
              ),
              const SectionHeader('Received', icon: Icons.payments_outlined),
              if (payments.isEmpty)
                Text(
                  'Nothing received yet. Money is recorded on a money receipt, under Collections.',
                  style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
                ),
              for (final p in payments)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: AppCard(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(child: Text(money(p['amount'] as String), style: text.titleMedium)),
                            collectionStatusChip(p['status'] as String),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          [
                            methodLabels[p['method']] ?? p['method'] as String,
                            if (p['reference'] != null) p['reference'] as String,
                            if (p['receipt_number'] != null) p['receipt_number'] as String,
                            'by ${p['collected_by']}',
                            dayLabel(p['collected_on'] as String),
                          ].join(' · '),
                          style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                        ),
                      ],
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

/// Money owed, by who owes it, the largest first. Admins and managers.
class ReceivablesScreen extends StatelessWidget {
  const ReceivablesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Receivables')),
      body: Loader<Map<String, dynamic>>(
        errorTitle: 'Could not load receivables',
        load: () async => await context.read<ApiClient>().get('/receivables') as Map<String, dynamic>,
        builder: (context, owed) {
          final parties = (owed['parties'] as List).cast<Map<String, dynamic>>();
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              AppCard(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Outstanding', style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted)),
                      Text('Rs ${owed['outstanding']}', style: text.headlineMedium),
                      const SizedBox(height: 4),
                      Text(
                        'Rs ${owed['overdue']} of it is overdue',
                        style: text.bodyMedium!.copyWith(
                          color: double.parse(owed['overdue'] as String) > 0 ? Palette.error : null,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SectionHeader('Who owes', icon: Icons.groups_outlined),
              if (parties.isEmpty) Text('Nobody owes anything.', style: text.bodyMedium),
              for (final p in parties)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: AppCard(
                    child: InkWell(
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(builder: (_) => PartyDuesScreen(party: p['party'] as String)),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(p['party'] as String, style: text.titleMedium),
                                  const SizedBox(height: 4),
                                  Text(
                                    'Rs ${p['outstanding']} on ${p['lr_count']} LR${p['lr_count'] == 1 ? '' : 's'}',
                                    style: text.bodyMedium,
                                  ),
                                  if (double.parse(p['overdue'] as String) > 0)
                                    Text(
                                      'Rs ${p['overdue']} overdue',
                                      style: text.bodyMedium!.copyWith(color: Palette.error),
                                    ),
                                ],
                              ),
                            ),
                            const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
                          ],
                        ),
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

/// The unpaid LRs of one party, oldest first. Tap one to see or record its payments.
class PartyDuesScreen extends StatefulWidget {
  const PartyDuesScreen({super.key, required this.party});

  final String party;

  @override
  State<PartyDuesScreen> createState() => _PartyDuesScreenState();
}

class _PartyDuesScreenState extends State<PartyDuesScreen> {
  final _loader = GlobalKey<LoaderState<List<Map<String, dynamic>>>>();

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(widget.party)),
      body: Loader<List<Map<String, dynamic>>>(
        key: _loader,
        errorTitle: 'Could not load the unpaid LRs',
        load: () async => (await context.read<ApiClient>().get('/receivables/lrs', query: {'party': widget.party})
                as List)
            .cast<Map<String, dynamic>>(),
        builder: (context, accounts) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (accounts.isEmpty) Text('Nothing is outstanding.', style: text.bodyMedium),
            for (final a in accounts)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AppCard(
                  child: InkWell(
                    onTap: () async {
                      await Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) =>
                              LrAccountScreen(lrId: a['lr_id'] as String, lrNumber: a['lr_number'] as String),
                        ),
                      );
                      await _loader.currentState?.reload();
                    },
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${a['lr_number']} · Rs ${a['balance']}', style: text.titleMedium),
                                const SizedBox(height: 4),
                                Text('booked ${dayLabel(a['lr_date'] as String)} · ${a['freight_by']}', style: text.bodyMedium),
                              ],
                            ),
                          ),
                          StatusChip(
                            dueLabel(a),
                            background: a['overdue'] as bool ? Palette.errorContainer : Palette.primaryContainer,
                            foreground: a['overdue'] as bool ? Palette.error : Palette.onPrimaryContainer,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
