import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import 'receipt_screens.dart' show askReason;

/// The owner's money trail: what was booked, collected, handed over and banked; who holds what;
/// and everything that needs a decision.
class MoneyTrailScreen extends StatefulWidget {
  const MoneyTrailScreen({super.key});

  @override
  State<MoneyTrailScreen> createState() => _MoneyTrailScreenState();
}

class _MoneyTrailScreenState extends State<MoneyTrailScreen> {
  String _period = 'today';
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Map<String, String> get _query {
    final now = DateTime.now();
    final from = _period == 'today' ? now : DateTime(now.year, now.month);
    return {'date_from': from.toIso8601String().substring(0, 10), 'date_to': now.toIso8601String().substring(0, 10)};
  }

  Widget _row(String label, String amount, {bool strong = false, Color? colour}) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Expanded(child: Text(label, style: strong ? text.titleMedium : text.bodyMedium)),
          Text(money(amount), style: (strong ? text.titleMedium : text.labelLarge)!.copyWith(color: colour)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Money trail')),
        body: Loader<Map<String, dynamic>>(
          key: _loader,
          errorTitle: 'Could not load the money trail',
          load: () async => await context.read<ApiClient>().get('/collections/overview', query: _query) as Map<String, dynamic>,
          builder: (context, o) {
            final text = Theme.of(context).textTheme;
            final custody = (o['custody'] as List).cast<Map<String, dynamic>>();
            final alerts = (o['exceptions'] as List).cast<Map<String, dynamic>>();
            final short = double.parse(o['shortages'] as String) > 0;
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                Segmented<String>(
                  options: const {'today': 'Today', 'month': 'This month'},
                  value: _period,
                  onChanged: (p) {
                    setState(() => _period = p);
                    _loader.currentState?.reload();
                  },
                ),
                const SizedBox(height: 16),
                AppCard(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    children: [
                      _row('Booked (LRs)', o['booked'] as String),
                      const Divider(height: 18),
                      _row('Collected in cash', o['collected_cash'] as String),
                      _row('Collected by UPI', o['collected_upi'] as String),
                      _row('Collected by cheque', o['collected_cheque'] as String),
                      _row('Paid straight to the bank', o['received_by_transfer'] as String),
                      const Divider(height: 18),
                      _row('Cash expected at handover', o['handed_over_expected'] as String),
                      _row('Cash counted at handover', o['handed_over_counted'] as String),
                      _row('Shortages', o['shortages'] as String, colour: short ? Palette.error : null),
                      const Divider(height: 18),
                      _row('Seen in the bank statement', o['banked'] as String, strong: true),
                    ],
                  ),
                ),
                const SectionHeader('Right now', icon: Icons.account_balance_wallet_outlined),
                AppCard(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    children: [
                      _row('Customers owe', o['receivable'] as String, strong: true),
                      _row('Deposited, not yet in the bank', o['deposits_in_transit'] as String),
                      _row('UPI not yet in the bank', o['upi_unconfirmed'] as String),
                      _row('Cheques not yet cleared', o['cheques_uncleared'] as String),
                      _row('Bank credits not yet matched', o['bank_credits_unallocated'] as String),
                    ],
                  ),
                ),
                if (custody.isNotEmpty) ...[
                  const SectionHeader('Who is holding money', icon: Icons.person_outline),
                  for (final c in custody)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: AppCard(
                        padding: const EdgeInsets.all(16),
                        child: Row(
                          children: [
                            Expanded(child: Text(c['name'] as String, style: text.titleMedium)),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text(money(c['cash'] as String), style: text.labelLarge),
                                Text('since ${dateTimeLabel(c['oldest'] as String)}', style: text.bodySmall),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                ],
                SectionHeader('Needs attention · ${alerts.length}', icon: Icons.flag_outlined),
                if (alerts.isEmpty)
                  const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Nothing to look at', body: 'Every rupee is where it should be.'),
                for (final a in alerts)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.error_outline, color: Palette.warning, size: 20),
                          const SizedBox(width: 10),
                          Expanded(child: Text(a['message'] as String, style: text.bodyMedium)),
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

/// Import the bank statement and deal with credits the app could not match itself.
class BankScreen extends StatefulWidget {
  const BankScreen({super.key});

  @override
  State<BankScreen> createState() => _BankScreenState();
}

class _BankScreenState extends State<BankScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();
  bool _importing = false;

  Future<void> _import() async {
    final picked = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['csv', 'xls', 'xlsx'], withData: true);
    final file = picked?.files.single;
    if (file == null || file.bytes == null || !mounted) return;
    final api = context.read<ApiClient>();
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _importing = true);
    try {
      final preview = await api.postFile('/bank/statements/preview', file.bytes!, file.name) as Map<String, dynamic>;
      if (!mounted) return;
      final go = await showDialog<bool>(context: context, builder: (_) => _PreviewDialog(preview: preview));
      if (go != true) return;
      final result = await api.postFile(
        '/bank/statements',
        file.bytes!,
        file.name,
        fields: {'layout': jsonEncode(preview['layout'])},
      ) as Map<String, dynamic>;
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            '${result['lines_new']} new lines. ${result['matched']} matched automatically; '
            '${result['unmatched_credits']} credits need you.',
          ),
        ),
      );
      await _loader.currentState?.reload();
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  Future<void> _allocate(Map<String, dynamic> line) async {
    final payer = await askReason(context, title: 'Who paid ${money(line['credit'] as String)}?', hint: 'Party name, as on their LRs');
    if (payer == null || !mounted) return;
    // A key per line: tapping twice cannot set the same bank credit against the customer twice.
    await _act('/bank/lines/${line['id']}/allocate', {'payer_name': payer}, 'Set against $payer\'s oldest LRs.', key: 'allocate-${line['id']}');
  }

  Future<void> _ignore(Map<String, dynamic> line) async {
    final note = await askReason(context, title: 'Not a customer payment?', hint: 'For example: bank interest');
    if (note == null || !mounted) return;
    await _act('/bank/lines/${line['id']}/ignore', {'note': note}, 'Marked as not a customer payment.');
  }

  Future<void> _act(String path, Map<String, dynamic> body, String done, {String? key}) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post(path, body, idempotencyKey: key);
      messenger.showSnackBar(SnackBar(content: Text(done)));
      await _loader.currentState?.reload();
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Bank statement')),
        bottomNavigationBar: BottomBar(
          children: [BusyButton(icon: Icons.upload_file, label: 'Import statement', busy: _importing, onPressed: _import)],
        ),
        body: Loader<List<dynamic>>(
          key: _loader,
          errorTitle: 'Could not load the statement lines',
          load: () async => await context.read<ApiClient>().get('/bank/lines', query: {'status': 'unmatched'}) as List,
          builder: (context, rows) {
            final text = Theme.of(context).textTheme;
            final lines = [for (final l in rows.cast<Map<String, dynamic>>()) if (double.parse(l['credit'] as String) > 0) l];
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro(
                  'Download the statement from ICICI net banking (CSV or Excel) and import it here, daily. '
                  'UPI, cheques and deposits are matched by themselves; what is left is below.',
                ),
                if (lines.isEmpty)
                  const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Everything is matched', body: 'No credit in the statement is waiting for you.'),
                for (final l in lines)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text(money(l['credit'] as String), style: text.titleMedium)),
                              Text(dayLabel(l['txn_date'] as String), style: text.bodySmall),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(l['narration'] as String, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
                          const SizedBox(height: 10),
                          Row(
                            children: [
                              Expanded(
                                child: FilledButton(
                                  style: FilledButton.styleFrom(minimumSize: const Size(0, 42)),
                                  onPressed: () => _allocate(l),
                                  child: const Text('Customer paid'),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: OutlinedButton(
                                  style: OutlinedButton.styleFrom(minimumSize: const Size(0, 42)),
                                  onPressed: () => _ignore(l),
                                  child: const Text('Not a payment'),
                                ),
                              ),
                            ],
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

class _PreviewDialog extends StatelessWidget {
  const _PreviewDialog({required this.preview});

  final Map<String, dynamic> preview;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final sample = (preview['sample'] as List).cast<Map<String, dynamic>>().take(5);
    final problems = (preview['problems'] as List).cast<String>();
    return AlertDialog(
      title: Text('${preview['lines_found']} lines found'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              preview['remembered'] as bool ? 'Read the same way as last time.' : 'Check these look right before importing:',
              style: text.bodySmall,
            ),
            const SizedBox(height: 10),
            for (final l in sample)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  '${dayLabel(l['txn_date'] as String)} · '
                  '${double.parse(l['credit'] as String) > 0 ? '+${money(l['credit'] as String)}' : '-${money(l['debit'] as String)}'}\n'
                  '${l['narration']}',
                  style: text.bodySmall,
                ),
              ),
            for (final p in problems) Text(p, style: text.bodySmall!.copyWith(color: Palette.warning)),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Import')),
      ],
    );
  }
}

/// Shortages waiting for the owner's decision, and those already decided.
class ShortagesScreen extends StatefulWidget {
  const ShortagesScreen({super.key});

  @override
  State<ShortagesScreen> createState() => _ShortagesScreenState();
}

class _ShortagesScreenState extends State<ShortagesScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();

  Future<void> _decide(Map<String, dynamic> s, String decision) async {
    final note = await askReason(context, title: 'Why?', hint: 'What was agreed with ${s['name']}');
    if (note == null || !mounted) return;
    final now = DateTime.now();
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/shortages/${s['id']}/decide', {
        'decision': decision,
        'note': note,
        if (decision == 'recover_from_salary') 'salary_month': DateTime(now.year, now.month).toIso8601String().substring(0, 10),
      });
      await _loader.currentState?.reload();
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Shortages')),
        body: Loader<List<dynamic>>(
          key: _loader,
          errorTitle: 'Could not load shortages',
          load: () async => await context.read<ApiClient>().get('/shortages') as List,
          builder: (context, rows) {
            final text = Theme.of(context).textTheme;
            final shortages = rows.cast<Map<String, dynamic>>();
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro('Money that should have been handed over or banked, but was not. Give the person a chance to explain first.'),
                if (shortages.isEmpty)
                  const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'No shortages', body: 'Every handover and deposit matched.'),
                for (final s in shortages)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text('${money(s['amount'] as String)} · ${s['name']}', style: text.titleMedium)),
                              StatusChip.tone(
                                switch (s['status']) {
                                  'recover_from_salary' => 'From salary',
                                  'written_off' => 'Written off',
                                  'found' => 'Found',
                                  _ => 'Open',
                                },
                                s['status'] == 'open' ? Tone.danger : Tone.neutral,
                              ),
                            ],
                          ),
                          Text(
                            'At ${s['source']} · ${dateTimeLabel(s['created_at'] as String)}${s['note'] != null ? ' · ${s['note']}' : ''}',
                            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                          ),
                          if (s['status'] == 'open') ...[
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 8,
                              children: [
                                OutlinedButton(onPressed: () => _decide(s, 'recover_from_salary'), child: const Text('Recover from salary')),
                                TextButton(onPressed: () => _decide(s, 'found'), child: const Text('Money found')),
                                TextButton(onPressed: () => _decide(s, 'written_off'), child: const Text('Write off')),
                              ],
                            ),
                          ],
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

const termsLabels = {
  'advance': 'Advance',
  'before_delivery': 'Before delivery',
  'at_delivery': 'At delivery',
  'credit': 'On credit',
};

/// How each customer pays: in advance, before or at delivery, or on credit up to a limit and age.
class CreditScreen extends StatefulWidget {
  const CreditScreen({super.key});

  @override
  State<CreditScreen> createState() => _CreditScreenState();
}

class _CreditScreenState extends State<CreditScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();

  Future<void> _edit([Map<String, dynamic>? terms]) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => _CreditForm(terms: terms)));
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Payment terms')),
        bottomNavigationBar: BottomBar(children: [BusyButton(icon: Icons.add, label: 'Add a customer', onPressed: _edit)]),
        body: Loader<List<dynamic>>(
          key: _loader,
          errorTitle: 'Could not load credit terms',
          load: () async => await context.read<ApiClient>().get('/credit-terms') as List,
          builder: (context, rows) {
            final text = Theme.of(context).textTheme;
            final terms = rows.cast<Map<String, dynamic>>();
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro(
                  'How each customer pays. Customers on credit get their goods before paying, while they owe less '
                  'than the limit and nothing is older than the days set. Everyone else pays at delivery.',
                ),
                if (terms.isEmpty)
                  const MessageView(card: true, icon: Icons.handshake_outlined, title: 'No terms set', body: 'Every customer pays at delivery.'),
                for (final t in terms)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      onTap: () => _edit(t),
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(t['payer_name'] as String, style: text.titleMedium),
                                Text(
                                  t['payment_terms'] == 'credit'
                                      ? '${t['credit_days']} days · owes ${money(t['outstanding'] as String)} of ${money(t['credit_limit'] as String)}'
                                      : '${termsLabels[t['payment_terms']]} · owes ${money(t['outstanding'] as String)}',
                                  style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                                ),
                              ],
                            ),
                          ),
                          if (!(t['is_active'] as bool)) StatusChip.tone('Paused', Tone.neutral),
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

class _CreditForm extends StatefulWidget {
  const _CreditForm({this.terms});

  final Map<String, dynamic>? terms;

  @override
  State<_CreditForm> createState() => _CreditFormState();
}

class _CreditFormState extends State<_CreditForm> with Submitter {
  late final _payer = TextEditingController(text: widget.terms?['payer_name'] as String? ?? '');
  late final _limit = TextEditingController(text: widget.terms?['credit_limit'] as String? ?? '');
  late final _days = TextEditingController(text: '${widget.terms?['credit_days'] ?? 30}');
  late final _note = TextEditingController(text: widget.terms?['note'] as String? ?? '');
  late String _terms = widget.terms?['payment_terms'] as String? ?? 'credit';
  late bool _reminders = widget.terms?['reminders'] as bool? ?? true;
  late bool _active = widget.terms?['is_active'] as bool? ?? true;

  @override
  void dispose() {
    for (final c in [_payer, _limit, _days, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final note = _note.text.trim();
    final credit = _terms == 'credit';
    await context.read<ApiClient>().put('/credit-terms', {
      'payer_name': _payer.text.trim(),
      'payment_terms': _terms,
      'credit_limit': credit ? _limit.text.trim() : null,
      'credit_days': credit ? int.parse(_days.text.trim()) : null,
      'note': note.isEmpty ? null : note,
      'reminders': _reminders,
      'is_active': _active,
    });
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: widget.terms == null ? 'Customer payment terms' : 'Edit payment terms',
        subtitle: 'Customers with no terms pay at delivery.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(
            label: 'Customer',
            controller: _payer,
            mandatory: true,
            capitalization: TextCapitalization.words,
            helper: 'As the name appears on their LRs.',
          ),
          ChoiceField<String>(
            label: 'Pays',
            options: termsLabels,
            value: _terms,
            onChanged: (v) => setState(() => _terms = v),
          ),
          if (_terms == 'credit') ...[
          AppTextField(
            label: 'Credit limit',
            controller: _limit,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter a limit above 0',
          ),
          AppTextField(
            label: 'Days allowed',
            controller: _days,
            mandatory: true,
            keyboardType: TextInputType.number,
            check: (v) {
              final n = int.tryParse(v);
              return n == null || n < 1 || n > 365 ? 'Between 1 and 365' : null;
            },
          ),
          ],
          AppTextField(
            label: 'Note',
            controller: _note,
            capitalization: TextCapitalization.sentences,
            helper: 'For special arrangements: what was agreed, and with whom.',
          ),
          SwitchField(
            label: 'Payment reminders',
            subtitle: 'Before the due date, on it, and weekly while overdue, by SMS and WhatsApp.',
            value: _reminders,
            onChanged: (v) => setState(() => _reminders = v),
          ),
          SwitchField(
            label: 'Active',
            subtitle: 'Pause to require your approval again.',
            value: _active,
            onChanged: (v) => setState(() => _active = v),
          ),
        ],
      );
}

/// Outstanding by age, and the customers to chase first.
class StuckMoneyScreen extends StatelessWidget {
  const StuckMoneyScreen({super.key});

  static const _buckets = {
    'not_due': 'Not due',
    'days_0_7': '0–7',
    'days_8_15': '8–15',
    'days_16_30': '16–30',
    'days_31_60': '31–60',
    'days_60_plus': '60+',
  };

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Where money is stuck')),
        body: Loader<(Map<String, dynamic>, Map<String, dynamic>)>(
          errorTitle: 'Could not load receivables',
          load: () async {
            final api = context.read<ApiClient>();
            final ageing = await api.get('/receivables/ageing') as Map<String, dynamic>;
            final stuck = await api.get('/receivables/priorities') as Map<String, dynamic>;
            return (ageing, stuck);
          },
          builder: (context, data) {
            final (ageing, stuck) = data;
            final text = Theme.of(context).textTheme;
            final figures = text.labelLarge!.copyWith(fontFeatures: const [FontFeature.tabularFigures()]);
            final totals = ageing['totals'] as Map<String, dynamic>;
            Widget list(String title, IconData icon, List<dynamic> rows, String Function(Map<String, dynamic>) line, String Function(Map<String, dynamic>) value) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(title, icon: icon),
                    if (rows.isEmpty) Text('None.', style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted)),
                    for (final r in rows.cast<Map<String, dynamic>>())
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: AppCard(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            children: [
                              Expanded(child: Text(line(r), style: text.bodyMedium)),
                              Text(value(r), style: figures),
                            ],
                          ),
                        ),
                      ),
                  ],
                );
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro('Days are counted past each LR\'s due date, which follows the customer\'s payment terms.'),
                AppCard(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    children: [
                      for (final b in _buckets.entries)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Row(
                            children: [
                              Expanded(child: Text(b.key == 'not_due' ? b.value : '${b.value} days late', style: text.bodyMedium)),
                              Text(money(totals[b.key] as String), style: figures),
                            ],
                          ),
                        ),
                      const Divider(height: 18),
                      Row(
                        children: [
                          Expanded(child: Text('Total owed', style: text.titleMedium)),
                          Text(money(totals['total'] as String), style: figures.copyWith(fontSize: 17)),
                        ],
                      ),
                    ],
                  ),
                ),
                list('Oldest overdue', Icons.history, stuck['oldest_overdue'] as List,
                    (r) => '${r['party']} · ${r['lr_number']} · ${r['days_overdue']} days', (r) => money(r['balance'] as String)),
                list('Biggest balances', Icons.account_balance_wallet_outlined, stuck['largest'] as List,
                    (r) => '${r['party']} · ${r['lr_count']} LRs', (r) => money(r['outstanding'] as String)),
                list('Near or over their limit', Icons.speed, stuck['near_limit'] as List,
                    (r) => '${r['party']} · limit ${money(r['credit_limit'] as String)}', (r) => '${r['used_pct']}%'),
                list('Pay late again and again', Icons.repeat, stuck['late_payers'] as List,
                    (r) => '${r['party']} · ${r['lrs_paid_late']} of ${r['lrs_paid']} paid late', (r) => '${r['average_days_late']} days'),
                const SectionHeader('By customer', icon: Icons.groups_outlined),
                for (final r in (ageing['rows'] as List).cast<Map<String, dynamic>>())
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: AppCard(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text(r['party'] as String, style: text.titleMedium)),
                              Text(money(r['total'] as String), style: figures),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(
                            [
                              for (final b in _buckets.entries)
                                if (double.parse(r[b.key] as String) > 0) '${b.value}: ${money(r[b.key] as String)}',
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
