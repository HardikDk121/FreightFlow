import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';

const _modes = {'cash': 'Cash', 'upi': 'UPI', 'neft': 'NEFT', 'cheque': 'Cheque'};

String _date(String iso) {
  final parts = iso.split('-');
  return '${parts[2]}-${parts[1]}-${parts[0]}';
}

/// "Due on delivery", "Due 04-10-2026", "Overdue since 04-10-2026".
String dueLabel(Map<String, dynamic> account) {
  final due = account['due_on'] as String?;
  if (due == null) return 'Due on delivery';
  return account['overdue'] as bool ? 'Overdue since ${_date(due)}' : 'Due ${_date(due)}';
}

/// What one LR is owed, each payment received against it, and a button to record another.
class LrAccountScreen extends StatefulWidget {
  const LrAccountScreen({super.key, required this.lrId, required this.lrNumber});

  final String lrId;
  final String lrNumber;

  @override
  State<LrAccountScreen> createState() => _LrAccountScreenState();
}

class _LrAccountScreenState extends State<LrAccountScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Future<void> _record(String balance) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => RecordPaymentScreen(lrId: widget.lrId, lrNumber: widget.lrNumber, balance: balance),
      ),
    );
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canRecord = context.select<Session, bool>((s) => s.user?.canBookLr ?? false);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text('Payments · ${widget.lrNumber}')),
      body: Loader<Map<String, dynamic>>(
        key: _loader,
        errorTitle: 'Could not load the payments',
        load: () async => await context.read<ApiClient>().get('/lrs/${widget.lrId}/account') as Map<String, dynamic>,
        builder: (context, account) {
          final payments = (account['payments'] as List).cast<Map<String, dynamic>>();
          final settled = double.parse(account['balance'] as String) <= 0;
          final overdue = account['overdue'] as bool;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              AppCard(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Balance', style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted)),
                      Text('Rs ${account['balance']}', style: text.headlineMedium),
                      const SizedBox(height: 8),
                      Text('Total Rs ${account['total']} · received Rs ${account['paid']}', style: text.bodyMedium),
                      Text('${account['payer']} pays (${account['freight_by']})', style: text.bodyMedium),
                      const SizedBox(height: 10),
                      settled
                          ? const StatusChip('Settled', background: Palette.successContainer, foreground: Palette.success)
                          : StatusChip(
                              dueLabel(account),
                              background: overdue ? Palette.errorContainer : Palette.primaryContainer,
                              foreground: overdue ? Palette.error : Palette.onPrimaryContainer,
                            ),
                      if (canRecord && !settled) ...[
                        const SizedBox(height: 16),
                        FilledButton(
                          onPressed: () => _record(account['balance'] as String),
                          child: const Text('Record a payment'),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              const SectionHeader('Received', icon: Icons.payments_outlined),
              if (payments.isEmpty) Text('Nothing received yet.', style: text.bodyMedium),
              for (final p in payments)
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
                                Text('Rs ${p['amount']}', style: text.titleMedium),
                                Text(
                                  [
                                    _modes[p['mode']]!,
                                    if (p['reference'] != null) p['reference'] as String,
                                    _date(p['received_on'] as String),
                                  ].join(' · '),
                                  style: text.bodyMedium,
                                ),
                                if (p['note'] != null) Text(p['note'] as String, style: text.bodySmall),
                              ],
                            ),
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

/// Take a payment against one LR. Pops with `true` once saved.
class RecordPaymentScreen extends StatefulWidget {
  const RecordPaymentScreen({super.key, required this.lrId, required this.lrNumber, required this.balance});

  final String lrId;
  final String lrNumber;
  final String balance;

  @override
  State<RecordPaymentScreen> createState() => _RecordPaymentScreenState();
}

class _RecordPaymentScreenState extends State<RecordPaymentScreen> with Submitter {
  late final _amount = TextEditingController(text: widget.balance);
  final _reference = TextEditingController();
  final _note = TextEditingController();
  String _mode = 'cash';

  @override
  void dispose() {
    for (final c in [_amount, _reference, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _checkAmount(String value) {
    final amount = double.tryParse(value);
    if (amount == null || amount <= 0) return 'Enter an amount above 0';
    return amount > double.parse(widget.balance) ? 'Only Rs ${widget.balance} is outstanding' : null;
  }

  Future<void> _save() async {
    final reference = _reference.text.trim();
    final note = _note.text.trim();
    await context.read<ApiClient>().post('/lrs/${widget.lrId}/payments', {
      'amount': _amount.text.trim(),
      'mode': _mode,
      if (reference.isNotEmpty) 'reference': reference,
      if (note.isNotEmpty) 'note': note,
    });
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Payment for ${widget.lrNumber}',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save payment',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(
            label: 'Amount received',
            controller: _amount,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: _checkAmount,
            helper: 'Rs ${widget.balance} is outstanding. Enter less for a part payment.',
          ),
          ChoiceField<String>(
            label: 'Paid by',
            options: _modes,
            value: _mode,
            onChanged: (mode) => setState(() => _mode = mode),
          ),
          if (_mode != 'cash')
            AppTextField(
              label: _mode == 'cheque' ? 'Cheque number' : 'Reference number',
              controller: _reference,
              capitalization: TextCapitalization.characters,
            ),
          AppTextField(label: 'Note', controller: _note, capitalization: TextCapitalization.sentences),
        ],
      );
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
                                Text('booked ${_date(a['lr_date'] as String)} · ${a['freight_by']}', style: text.bodyMedium),
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
