import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/pdf_screen.dart';
import '../payments/payments_screens.dart' show collectionStatusChip, dueLabel, methodLabels;

const _outcomes = {'paid': 'Paid in full', 'part_paid': 'Part paid', 'come_later': 'Come later', 'refused': 'Refused'};

const _custody = {
  'with_collector': 'With the collector',
  'handed_over': 'At the office',
  'deposited': 'Deposited, not yet in the bank',
  'awaiting_bank': 'Not yet in the bank',
  'in_bank': 'In the bank',
  'failed': 'Failed',
  'legacy': 'Recorded before checks',
};

StatusChip receiptStatusChip(Map<String, dynamic> r) => switch (r['status']) {
      'settled' => StatusChip.tone('Settled', Tone.success),
      'cancelled' => StatusChip.tone('Cancelled', Tone.danger),
      _ => r['promised_on'] != null
          ? StatusChip.tone('Promised ${dayLabel(r['promised_on'] as String)}', Tone.warning)
          : StatusChip.tone('${money(r['balance'] as String)} due', Tone.info),
    };

/// One money receipt in a list.
class ReceiptCard extends StatelessWidget {
  const ReceiptCard({super.key, required this.receipt, required this.onTap});

  final Map<String, dynamic> receipt;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final lrs = [for (final l in (receipt['lines'] as List)) l['lr_number'] as String];
    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(receipt['receipt_number'] as String, style: text.titleMedium)),
              receiptStatusChip(receipt),
            ],
          ),
          const SizedBox(height: 6),
          Text(receipt['payer_name'] as String, style: text.labelLarge),
          Text(
            '${lrs.join(', ')} · ${money(receipt['amount'] as String)}',
            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
          ),
        ],
      ),
    );
  }
}

/// Issue a receipt: choose who pays, then which of their LRs. The amount comes from the LRs.
class IssueReceiptScreen extends StatefulWidget {
  const IssueReceiptScreen({super.key});

  @override
  State<IssueReceiptScreen> createState() => _IssueReceiptScreenState();
}

class _IssueReceiptScreenState extends State<IssueReceiptScreen> with Submitter {
  final _key = newIdempotencyKey();
  final _search = TextEditingController();
  final _phone = TextEditingController();
  String? _payer;
  List<Map<String, dynamic>>? _lrs;
  final Set<String> _chosen = {};

  /// Charges added at delivery, per LR: labour, door delivery (DC) and demurrage.
  final Map<String, Map<String, TextEditingController>> _charges = {};
  static const _chargeKinds = {'labour': 'Labour', 'dc_charge': 'DC charge', 'demurrage': 'Demurrage'};

  Map<String, TextEditingController> _chargesFor(String lrId) => _charges.putIfAbsent(
        lrId,
        () => {for (final kind in _chargeKinds.keys) kind: TextEditingController()..addListener(() => setState(() {}))},
      );

  double _extra(String lrId) => (_charges[lrId]?.values ?? const <TextEditingController>[])
      .fold<double>(0, (sum, c) => sum + (double.tryParse(c.text.trim()) ?? 0));

  @override
  void dispose() {
    _search.dispose();
    _phone.dispose();
    for (final set in _charges.values) {
      for (final c in set.values) {
        c.dispose();
      }
    }
    super.dispose();
  }

  Future<void> _choosePayer(String payer) async {
    setState(() {
      _payer = payer;
      _lrs = null;
      _chosen.clear();
    });
    try {
      final lrs = await context.read<ApiClient>().get('/receivables/lrs', query: {'party': payer}) as List;
      if (!mounted) return;
      setState(() {
        _lrs = lrs.cast<Map<String, dynamic>>();
        _chosen.addAll(_lrs!.map((a) => a['lr_id'] as String));
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  Future<void> _issue() async {
    if (_chosen.isEmpty) throw const ApiException(0, 'Choose at least one LR.');
    final phone = _phone.text.trim();
    final charges = [
      for (final lrId in _chosen)
        for (final entry in _chargesFor(lrId).entries)
          if ((double.tryParse(entry.value.text.trim()) ?? 0) > 0)
            {'lr_id': lrId, 'kind': entry.key, 'amount': entry.value.text.trim()},
    ];
    final receipt = await context.read<ApiClient>().post(
      '/receipts',
      {'lr_ids': _chosen.toList(), 'charges': charges, if (phone.isNotEmpty) 'payer_phone': phone},
      idempotencyKey: _key,
    ) as Map<String, dynamic>;
    if (!mounted) return;
    await Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(builder: (_) => ReceiptScreen(receiptId: receipt['id'] as String)),
    );
  }

  Widget _payerList() => Loader<Map<String, dynamic>>(
        errorTitle: 'Could not load who owes money',
        load: () async => await context.read<ApiClient>().get('/receivables') as Map<String, dynamic>,
        builder: (context, owed) {
          final text = Theme.of(context).textTheme;
          final query = _search.text.trim().toLowerCase();
          final parties = [
            for (final p in (owed['parties'] as List).cast<Map<String, dynamic>>())
              if (query.isEmpty || (p['party'] as String).toLowerCase().contains(query)) p,
          ];
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            children: [
              const PageIntro('Choose who pays. Only parties that owe something are listed.'),
              TextField(
                controller: _search,
                onChanged: (_) => setState(() {}),
                decoration: const InputDecoration(hintText: 'Search party', prefixIcon: Icon(Icons.search)),
              ),
              const SizedBox(height: 12),
              if (parties.isEmpty) MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Nothing owed', body: 'No party matches, or nobody owes anything.'),
              for (final p in parties)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: AppCard(
                    onTap: () => _choosePayer(p['party'] as String),
                    padding: const EdgeInsets.all(16),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(p['party'] as String, style: text.titleMedium),
                              Text(
                                '${money(p['outstanding'] as String)} on ${p['lr_count']} LR${p['lr_count'] == 1 ? '' : 's'}',
                                style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                              ),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
                      ],
                    ),
                  ),
                ),
            ],
          );
        },
      );

  @override
  Widget build(BuildContext context) {
    if (_payer == null) {
      return Scaffold(appBar: AppBar(title: const Text('New money receipt')), body: _payerList());
    }
    final lrs = _lrs;
    final total = (lrs ?? const [])
        .where((a) => _chosen.contains(a['lr_id']))
        .fold<double>(0, (sum, a) => sum + double.parse(a['balance'] as String) + _extra(a['lr_id'] as String));
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Receipt for $_payer',
      subtitle: 'The amount is what the chosen LRs owe now. It cannot be typed in.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Issue receipt',
      onSubmit: lrs == null ? null : () => submit(_issue),
      footer: Row(
        children: [
          Expanded(child: Text('Receipt total', style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted))),
          Text(rupees(total), style: text.titleLarge),
        ],
      ),
      children: [
        if (lrs == null) const SizedBox(height: 120, child: Center(child: CircularProgressIndicator())),
        for (final a in lrs ?? const <Map<String, dynamic>>[])
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              child: CheckboxListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
                value: _chosen.contains(a['lr_id']),
                onChanged: (on) => setState(() => on == true ? _chosen.add(a['lr_id'] as String) : _chosen.remove(a['lr_id'])),
                title: Text('${a['lr_number']} · ${money(a['balance'] as String)}', style: text.titleMedium),
                subtitle: Text('Booked ${dayLabel(a['lr_date'] as String)} · ${dueLabel(a)}', style: text.bodySmall),
              ),
            ),
          ),
        if ((lrs ?? const []).any((a) => _chosen.contains(a['lr_id']))) ...[
          const SectionHeader('Charges at delivery', icon: Icons.add_card_outlined),
          for (final a in lrs!.where((a) => _chosen.contains(a['lr_id'])))
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_chosen.length > 1) Text(a['lr_number'] as String, style: text.labelLarge),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (final kind in _chargeKinds.entries) ...[
                        if (kind.key != 'labour') const SizedBox(width: 8),
                        Expanded(
                          child: AppTextField(
                            label: kind.value,
                            controller: _chargesFor(a['lr_id'] as String)[kind.key]!,
                            keyboardType: const TextInputType.numberWithOptions(decimal: true),
                            check: (v) => (double.tryParse(v) ?? -1) < 0 ? 'Amount' : null,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
        ],
        const SizedBox(height: 8),
        AppTextField(
          label: "Customer's mobile",
          controller: _phone,
          keyboardType: TextInputType.phone,
          hint: '10-digit mobile',
          helper: 'Every payment recorded is sent here by SMS and WhatsApp, so the customer can say if it is wrong.',
        ),
        TextButton(onPressed: () => setState(() => _payer = null), child: const Text('Choose another party')),
      ],
    );
  }
}

/// One receipt: what it covers, every visit, every payment and where that money is now.
class ReceiptScreen extends StatefulWidget {
  const ReceiptScreen({super.key, required this.receiptId});

  final String receiptId;

  @override
  State<ReceiptScreen> createState() => _ReceiptScreenState();
}

class _ReceiptScreenState extends State<ReceiptScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Future<void> _visit(Map<String, dynamic> receipt) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => VisitScreen(receipt: receipt)));
    if (saved == true) await _loader.currentState?.reload();
  }

  Future<void> _cancel(Map<String, dynamic> receipt) async {
    final reason = await askReason(context, title: 'Cancel ${receipt['receipt_number']}?', hint: 'For example: wrong LRs');
    if (reason == null || !mounted) return;
    try {
      await context.read<ApiClient>().post('/receipts/${widget.receiptId}/cancel', {'reason': reason});
      await _loader.currentState?.reload();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  void _print(Map<String, dynamic> receipt) => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PdfScreen(
            title: receipt['receipt_number'] as String,
            path: '/receipts/${widget.receiptId}/pdf',
            fileName: '${receipt['receipt_number']}.pdf',
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user;
    final text = Theme.of(context).textTheme;
    return Loader<Map<String, dynamic>>(
      key: _loader,
      errorTitle: 'Could not load the receipt',
      load: () async => await context.read<ApiClient>().get('/receipts/${widget.receiptId}') as Map<String, dynamic>,
      builder: (context, r) {
        final open = r['status'] == 'open';
        final collections = (r['collections'] as List).cast<Map<String, dynamic>>();
        final visits = (r['visits'] as List).cast<Map<String, dynamic>>();
        return Scaffold(
          appBar: AppBar(
            title: Text(r['receipt_number'] as String),
            actions: [
              IconButton(tooltip: 'Print', icon: const Icon(Icons.print_outlined), onPressed: () => _print(r)),
            ],
          ),
          bottomNavigationBar: open && (user?.canCollect ?? false)
              ? BottomBar(children: [BusyButton(icon: Icons.how_to_reg_outlined, label: 'Record a visit', onPressed: () => _visit(r))])
              : null,
          body: ListView(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
            children: [
              DarkPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(r['payer_name'] as String, style: onInk(text.titleLarge!))),
                        receiptStatusChip(r),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(child: MetricTile(value: money(r['balance'] as String), label: 'Still to collect', onDark: true)),
                        Expanded(child: MetricTile(value: money(r['collected'] as String), label: 'Collected', onDark: true)),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      'Issued by ${r['issued_by']} · ${dateTimeLabel(r['issued_at'] as String)}'
                      '${r['payer_phone'] == null ? ' · no phone: the customer is not told' : ' · customer ${r['payer_phone']}'}',
                      style: onInk(text.bodySmall!, muted: true),
                    ),
                    if (r['cancel_reason'] != null)
                      Text('Cancelled: ${r['cancel_reason']}', style: onInk(text.bodySmall!, muted: true)),
                  ],
                ),
              ),
              const SectionHeader('LRs', icon: Icons.receipt_long_outlined),
              AppCard(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(
                  children: [
                    for (final l in (r['lines'] as List).cast<Map<String, dynamic>>())
                      ListTile(
                        title: Text('${l['lr_number']} · ${l['to_city']}', style: text.titleMedium),
                        subtitle: Text('Booked ${dayLabel(l['lr_date'] as String)}', style: text.bodySmall),
                        trailing: Text(
                          double.parse(l['balance'] as String) <= 0 ? 'Paid' : '${money(l['balance'] as String)} due',
                          style: text.labelLarge,
                        ),
                      ),
                  ],
                ),
              ),
              if (collections.isNotEmpty) ...[
                const SectionHeader('Payments', icon: Icons.payments_outlined),
                for (final c in collections)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  '${money(c['amount'] as String)} · ${methodLabels[c['method']]}',
                                  style: text.titleMedium,
                                ),
                              ),
                              collectionStatusChip(c['status'] as String),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(
                            [
                              'by ${c['collected_by']}',
                              dateTimeLabel(c['collected_at'] as String),
                              if (c['utr'] != null) 'UTR ${c['utr']}',
                              if (c['cheque_number'] != null) 'cheque ${c['cheque_bank']} ${c['cheque_number']}',
                              _custody[c['custody']] ?? '',
                              if (c['failed_reason'] != null) c['failed_reason'] as String,
                            ].join(' · '),
                            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
              if (visits.isNotEmpty) ...[
                const SectionHeader('Visits', icon: Icons.directions_walk),
                for (final v in visits.reversed)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text(
                      '${dateTimeLabel(v['visited_at'] as String)} · ${v['collector']} · ${_outcomes[v['outcome']]}'
                      '${v['promised_on'] != null ? ' by ${dayLabel(v['promised_on'] as String)}' : ''}'
                      '${v['note'] != null ? ': ${v['note']}' : ''}',
                      style: text.bodyMedium,
                    ),
                  ),
              ],
              if (open && collections.isEmpty && (user?.canEditMasterData ?? false))
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: TextButton(
                    style: TextButton.styleFrom(foregroundColor: Palette.error),
                    onPressed: () => _cancel(r),
                    child: const Text('Cancel this receipt'),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

/// Ask for a short reason; null if the person backs out.
Future<String?> askReason(BuildContext context, {required String title, required String hint}) =>
    showDialog<String>(context: context, builder: (_) => _ReasonDialog(title: title, hint: hint));

class _ReasonDialog extends StatefulWidget {
  const _ReasonDialog({required this.title, required this.hint});

  final String title;
  final String hint;

  @override
  State<_ReasonDialog> createState() => _ReasonDialogState();
}

class _ReasonDialogState extends State<_ReasonDialog> {
  final _reason = TextEditingController();

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.title),
        content: TextField(
          controller: _reason,
          autofocus: true,
          maxLength: 200,
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(hintText: widget.hint),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Back')),
          TextButton(
            onPressed: _reason.text.trim().length < 3 ? null : () => Navigator.of(context).pop(_reason.text.trim()),
            child: const Text('Confirm'),
          ),
        ],
      );
}

/// What happened at the customer. Pops with `true` once saved.
class VisitScreen extends StatefulWidget {
  const VisitScreen({super.key, required this.receipt});

  final Map<String, dynamic> receipt;

  @override
  State<VisitScreen> createState() => _VisitScreenState();
}

class _VisitScreenState extends State<VisitScreen> with Submitter {
  /// One key for this visit, so a retried save records the payment once.
  final _key = newIdempotencyKey();
  String _outcome = 'paid';
  String _method = 'cash';
  late final _amount = TextEditingController(text: widget.receipt['balance'] as String);
  final _utr = TextEditingController();
  final _chequeNumber = TextEditingController();
  final _chequeBank = TextEditingController();
  final _note = TextEditingController();
  DateTime? _promised;

  @override
  void dispose() {
    for (final c in [_amount, _utr, _chequeNumber, _chequeBank, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  bool get _paying => _outcome == 'paid' || _outcome == 'part_paid';

  Future<void> _pickPromise() async {
    final today = DateUtils.dateOnly(DateTime.now());
    final picked = await showDatePicker(
      context: context,
      firstDate: today,
      lastDate: today.add(const Duration(days: 90)),
      initialDate: _promised ?? today.add(const Duration(days: 1)),
    );
    if (picked != null) setState(() => _promised = picked);
  }

  Future<void> _save() async {
    if (_outcome == 'come_later' && _promised == null) {
      throw const ApiException(0, 'Choose the date the customer promised to pay.');
    }
    final note = _note.text.trim();
    await context.read<ApiClient>().post(idempotencyKey: _key, '/receipts/${widget.receipt['id']}/visits', {
      'outcome': _outcome,
      if (_promised != null && _outcome == 'come_later') 'promised_on': _promised!.toIso8601String().substring(0, 10),
      if (note.isNotEmpty) 'note': note,
      if (_paying)
        'payment': {
          'method': _method,
          'amount': _amount.text.trim(),
          if (_method == 'upi') 'utr': _utr.text.trim(),
          if (_method == 'cheque') 'cheque_number': _chequeNumber.text.trim(),
          if (_method == 'cheque') 'cheque_bank': _chequeBank.text.trim(),
        },
    });
    if (mounted) Navigator.of(context).pop(true);
  }

  String? _checkAmount(String value) {
    final amount = double.tryParse(value);
    final balance = double.parse(widget.receipt['balance'] as String);
    if (amount == null || amount <= 0) return 'Enter an amount above 0';
    if (amount > balance) return 'Only ${money(widget.receipt['balance'] as String)} is left';
    if (_outcome == 'paid' && amount != balance) return 'Paid in full is ${money(widget.receipt['balance'] as String)}';
    if (_outcome == 'part_paid' && amount == balance) return 'That is the full amount: choose Paid in full';
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Visit · ${widget.receipt['receipt_number']}',
      subtitle: '${widget.receipt['payer_name']} · ${money(widget.receipt['balance'] as String)} to collect',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Save visit',
      onSubmit: () => submit(_save),
      children: [
        ChoiceField<String>(
          label: 'What happened',
          options: _outcomes,
          value: _outcome,
          onChanged: (v) => setState(() {
            _outcome = v;
            if (v == 'paid') _amount.text = widget.receipt['balance'] as String;
          }),
        ),
        if (_paying) ...[
          ChoiceField<String>(
            label: 'Paid by',
            options: const {'cash': 'Cash', 'upi': 'UPI to company account', 'cheque': 'Cheque'},
            value: _method,
            onChanged: (v) => setState(() => _method = v),
          ),
          AppTextField(
            label: 'Amount received',
            controller: _amount,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: _checkAmount,
            helper: _method == 'cash' ? 'Cash over Rs 25,000 on one receipt goes to the owner or the bank.' : null,
          ),
          if (_method == 'upi')
            AppTextField(
              label: 'UTR from the customer\'s payment screen',
              controller: _utr,
              mandatory: true,
              hint: '12 digits',
              keyboardType: TextInputType.number,
              check: (v) => RegExp(r'^[0-9]{12}$').hasMatch(v) ? null : 'The UTR has 12 digits',
              helper: 'Checked against the company bank statement. It counts only when it appears there.',
            ),
          if (_method == 'cheque') ...[
            AppTextField(
              label: 'Cheque number',
              controller: _chequeNumber,
              mandatory: true,
              hint: '6 digits',
              keyboardType: TextInputType.number,
              check: (v) => RegExp(r'^[0-9]{6}$').hasMatch(v) ? null : 'A cheque number has 6 digits',
            ),
            AppTextField(label: 'Bank', controller: _chequeBank, mandatory: true, capitalization: TextCapitalization.characters),
          ],
        ],
        if (_outcome == 'come_later')
          PickerField(
            label: 'Promised to pay by',
            value: _promised == null ? null : dayLabel(_promised!.toIso8601String().substring(0, 10)),
            placeholder: 'Choose a date',
            icon: Icons.calendar_today_outlined,
            onTap: _pickPromise,
          ),
        AppTextField(
          label: 'Note',
          controller: _note,
          mandatory: _outcome == 'refused',
          lines: 2,
          capitalization: TextCapitalization.sentences,
        ),
        if (_paying)
          Text(
            'The customer gets an SMS and WhatsApp with this amount.',
            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
          ),
      ],
    );
  }
}
