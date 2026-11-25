import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../validation.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/phone_field.dart';

const _expenseKinds = {
  'loading_labour': 'Loading labour',
  'unloading_labour': 'Unloading labour',
  'broker_commission': 'Broker commission',
  'other': 'Other',
};
const _deductionReasons = {'shortage': 'Goods short', 'damage': 'Goods damaged', 'late': 'Late delivery', 'other': 'Other'};
const _methods = {'cash': 'Cash', 'upi': 'UPI', 'cheque': 'Cheque', 'bank_transfer': 'Bank transfer'};
const _paymentKinds = {'advance': 'Advance', 'balance': 'Balance', 'reversal': 'Reverse a payment'};

String _rs(dynamic v) => v == null ? '-' : money(v as String);

/// Truck owners and brokers the company hires trucks from.
class VendorsScreen extends StatefulWidget {
  const VendorsScreen({super.key});

  @override
  State<VendorsScreen> createState() => _VendorsScreenState();
}

class _VendorsScreenState extends State<VendorsScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();

  Future<void> _edit([Map<String, dynamic>? vendor]) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => _VendorForm(vendor: vendor)));
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Truck owners')),
        bottomNavigationBar: BottomBar(children: [BusyButton(icon: Icons.add, label: 'Add a truck owner', onPressed: _edit)]),
        body: Loader<List<dynamic>>(
          key: _loader,
          cacheKey: 'vendors',
          errorTitle: 'Could not load truck owners',
          load: () async => await context.read<ApiClient>().get('/vendors') as List,
          builder: (context, rows) {
            final text = Theme.of(context).textTheme;
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro('Everyone you hire trucks from. Their phone is used to send requests for quotes.'),
                for (final v in rows.cast<Map<String, dynamic>>())
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      onTap: () => _edit(v),
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(v['name'] as String, style: text.titleMedium),
                                Text(
                                  [v['kind'] == 'broker' ? 'Broker' : 'Truck owner', if (v['phone'] != null) v['phone'] as String].join(' · '),
                                  style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                                ),
                              ],
                            ),
                          ),
                          if (!(v['is_active'] as bool)) StatusChip.tone('Inactive', Tone.neutral),
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

class _VendorForm extends StatefulWidget {
  const _VendorForm({this.vendor});

  final Map<String, dynamic>? vendor;

  @override
  State<_VendorForm> createState() => _VendorFormState();
}

class _VendorFormState extends State<_VendorForm> with Submitter {
  late final _name = TextEditingController(text: widget.vendor?['name'] as String? ?? '');
  late final _phone = TextEditingController(text: widget.vendor?['phone'] as String? ?? '');
  late final _pan = TextEditingController(text: widget.vendor?['pan'] as String? ?? '');
  late final _bank = TextEditingController(text: widget.vendor?['bank_details'] as String? ?? '');
  late String _kind = widget.vendor?['kind'] as String? ?? 'truck_owner';
  late bool _active = widget.vendor?['is_active'] as bool? ?? true;

  @override
  void dispose() {
    for (final c in [_name, _phone, _pan, _bank]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    String? orNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
    final body = {'name': _name.text.trim(), 'kind': _kind, 'phone': orNull(_phone), 'pan': orNull(_pan), 'bank_details': orNull(_bank), 'is_active': _active};
    final api = context.read<ApiClient>();
    final vendor = widget.vendor;
    if (vendor == null) {
      await api.post('/vendors', body);
    } else {
      await api.put('/vendors/${vendor['id']}', body);
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: widget.vendor == null ? 'Add truck owner' : 'Edit truck owner',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(label: 'Name', controller: _name, mandatory: true, capitalization: TextCapitalization.words, check: businessName),
          ChoiceField<String>(label: 'Kind', options: const {'truck_owner': 'Truck owner', 'broker': 'Broker'}, value: _kind, onChanged: (v) => setState(() => _kind = v)),
          PhoneField(controller: _phone),
          AppTextField(label: 'PAN', controller: _pan, capitalization: TextCapitalization.characters, hint: 'ABCDE1234F', check: pan),
          AppTextField(
            label: 'Bank details',
            controller: _bank,
            lines: 3,
            helper: 'Account name, number and IFSC, for paying the hire.',
            check: (v) => v.trim().length > 240
                ? 'Use at most 240 characters.'
                : RegExp(r'[0-9]').allMatches(v).length < 6
                    ? 'Include the account number (and IFSC), or leave this empty.'
                    : null,
          ),
          if (widget.vendor != null) SwitchField(label: 'Active', value: _active, onChanged: (v) => setState(() => _active = v)),
        ],
      );
}

/// One trip's money: what it carried, the hire agreed with the truck owner, payments to them,
/// deductions, office expenses, and what is left.
class TripMoneyScreen extends StatefulWidget {
  const TripMoneyScreen({super.key, required this.tripId, required this.title});

  final String tripId;
  final String title;

  @override
  State<TripMoneyScreen> createState() => _TripMoneyScreenState();
}

class _TripMoneyScreenState extends State<TripMoneyScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Future<void> _open(Widget form) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => form));
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Loader<Map<String, dynamic>>(
        key: _loader,
        errorTitle: 'Could not load the trip\'s money',
        load: () async => await context.read<ApiClient>().get('/trips/${widget.tripId}/money') as Map<String, dynamic>,
        builder: (context, m) {
          final text = Theme.of(context).textTheme;
          final hired = m['hire'] != null;
          final margin = m['margin'] == null ? null : double.parse(m['margin'] as String);
          Widget lines(String title, IconData icon, List<dynamic> rows, Map<String, String> labels) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SectionHeader(title, icon: icon),
                  if (rows.isEmpty) Text('None.', style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted)),
                  for (final l in rows.cast<Map<String, dynamic>>())
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              '${labels[l['kind']] ?? l['kind']} · ${dateTimeLabel(l['at'] as String)} · ${l['by']}'
                              '${l['method'] != null ? ' · ${_methods[l['method']]}' : ''}'
                              '${l['reference'] != null ? ' ${l['reference']}' : ''}'
                              '${l['note'] != null ? '\n${l['note']}' : ''}',
                              style: text.bodySmall,
                            ),
                          ),
                          Text((l['kind'] == 'reversal' ? '−' : '') + _rs(l['amount']), style: text.labelLarge),
                        ],
                      ),
                    ),
                ],
              );
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            children: [
              DarkPanel(
                child: Column(
                  children: [
                    Row(
                      children: [
                        Expanded(child: MetricTile(value: _rs(m['revenue']), label: 'Freight carried', onDark: true)),
                        Expanded(child: MetricTile(value: _rs(m['hire']), label: 'Truck hire', onDark: true)),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        Expanded(
                          child: MetricTile(
                            value: margin == null ? '-' : rupees(margin),
                            label: m['margin_pct'] == null ? 'Left for us' : 'Left for us · ${m['margin_pct']}%',
                            onDark: true,
                          ),
                        ),
                        Expanded(child: MetricTile(value: _rs(m['owed_to_owner']), label: 'Still owed to owner', onDark: true)),
                      ],
                    ),
                  ],
                ),
              ),
              if (margin != null && margin < 0)
                const Padding(padding: EdgeInsets.only(top: 12), child: ErrorBanner('This trip loses money: the hire is more than the freight it carries.')),
              const SizedBox(height: 12),
              if (!hired)
                const PageIntro('No hire recorded yet. Enter what was agreed with the truck owner to see what this trip earns.'),
              if (hired) Text('Hired from ${m['vendor_name']}', style: text.titleMedium),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (user.can('vendors.manage'))
                    OutlinedButton.icon(
                      icon: const Icon(Icons.handshake_outlined),
                      label: Text(hired ? 'Change hire' : 'Record hire'),
                      onPressed: () => _open(_HireForm(tripId: widget.tripId, current: m)),
                    ),
                  if (hired && user.can('vendors.pay'))
                    FilledButton.icon(
                      icon: const Icon(Icons.payments_outlined),
                      label: const Text('Pay owner'),
                      onPressed: () => _open(_PaymentForm(tripId: widget.tripId, owed: m['owed_to_owner'] as String)),
                    ),
                  if (hired && user.can('vendors.manage'))
                    OutlinedButton.icon(
                      icon: const Icon(Icons.remove_circle_outline),
                      label: const Text('Deduct'),
                      onPressed: () => _open(_AmountForm(tripId: widget.tripId, kind: 'deductions')),
                    ),
                  if (user.can('vendors.manage'))
                    OutlinedButton.icon(
                      icon: const Icon(Icons.receipt_long_outlined),
                      label: const Text('Add expense'),
                      onPressed: () => _open(_AmountForm(tripId: widget.tripId, kind: 'expenses')),
                    ),
                ],
              ),
              lines('Paid to the truck owner', Icons.payments_outlined, m['payments'] as List, _paymentKinds),
              lines('Deductions', Icons.remove_circle_outline, m['deduction_lines'] as List, _deductionReasons),
              lines('Office expenses', Icons.receipt_long_outlined, m['expense_lines'] as List, _expenseKinds),
            ],
          );
        },
      ),
    );
  }
}

class _HireForm extends StatefulWidget {
  const _HireForm({required this.tripId, required this.current});

  final String tripId;
  final Map<String, dynamic> current;

  @override
  State<_HireForm> createState() => _HireFormState();
}

class _HireFormState extends State<_HireForm> with Submitter {
  late final _amount = TextEditingController(text: widget.current['hire'] as String? ?? '');
  final _note = TextEditingController();
  late String? _vendor = widget.current['vendor_id'] as String?;
  String? _rfq;
  List<Map<String, dynamic>> _vendors = const [];
  List<Map<String, dynamic>> _awarded = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    final vendors = (await api.get('/vendors') as List).cast<Map<String, dynamic>>();
    final rfqs = (await api.get('/rfqs', query: {'rfq_status': 'awarded'}) as List).cast<Map<String, dynamic>>();
    if (mounted) {
      setState(() {
        _vendors = [for (final v in vendors) if (v['is_active'] as bool) v];
        _awarded = rfqs;
      });
    }
  }

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  /// Taking the hire from an awarded request fills in its owner and price.
  void _useRfq(String? id) {
    setState(() => _rfq = id);
    if (id == null) return;
    final rfq = _awarded.firstWhere((r) => r['id'] == id);
    final quote = (rfq['quotes'] as List).cast<Map<String, dynamic>>().firstWhere((q) => q['id'] == rfq['awarded_quote_id']);
    setState(() {
      _vendor = quote['vendor_id'] as String;
      _amount.text = quote['amount'] as String;
    });
  }

  Future<void> _save() async {
    if (_vendor == null) throw const ApiException(0, 'Choose the truck owner.');
    final note = _note.text.trim();
    await context.read<ApiClient>().put('/trips/${widget.tripId}/hire', {
      'vendor_id': _vendor,
      'hire_amount': _amount.text.trim(),
      if (_rfq != null) 'rfq_id': _rfq,
      if (note.isNotEmpty) 'note': note,
    });
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Truck hire',
        subtitle: 'What was agreed with the truck owner for this trip. It cannot change once they have been paid.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save hire',
        onSubmit: () => submit(_save),
        children: [
          if (_awarded.isNotEmpty)
            ChoiceField<String?>(
              label: 'From a request for quotes',
              options: {null: 'No', for (final r in _awarded) r['id'] as String: 'RFQ-${r['rfq_number']} to ${r['destination']}'},
              value: _rfq,
              onChanged: _useRfq,
            ),
          ChoiceField<String?>(
            label: 'Truck owner',
            options: {null: 'Choose…', for (final v in _vendors) v['id'] as String: v['name'] as String},
            value: _vendor,
            onChanged: (v) => setState(() => _vendor = v),
          ),
          AppTextField(
            label: 'Hire agreed',
            controller: _amount,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter the amount',
          ),
          AppTextField(label: 'Note', controller: _note, capitalization: TextCapitalization.sentences),
        ],
      );
}

class _PaymentForm extends StatefulWidget {
  const _PaymentForm({required this.tripId, required this.owed});

  final String tripId;
  final String owed;

  @override
  State<_PaymentForm> createState() => _PaymentFormState();
}

class _PaymentFormState extends State<_PaymentForm> with Submitter {
  final _key = newIdempotencyKey();
  final _amount = TextEditingController();
  final _reference = TextEditingController();
  final _note = TextEditingController();
  String _kind = 'advance';
  String _method = 'bank_transfer';

  @override
  void dispose() {
    for (final c in [_amount, _reference, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    String? orNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
    await context.read<ApiClient>().post(
      '/trips/${widget.tripId}/owner-payments',
      {'kind': _kind, 'amount': _amount.text.trim(), 'method': _method, 'reference': orNull(_reference), 'note': orNull(_note)},
      idempotencyKey: _key,
    );
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Pay the truck owner',
        subtitle: 'Owed now: ${money(widget.owed)}. The balance is paid after delivery, so shortages can be deducted first.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Record payment',
        onSubmit: () => submit(_save),
        children: [
          ChoiceField<String>(label: 'Payment', options: _paymentKinds, value: _kind, onChanged: (v) => setState(() => _kind = v)),
          AppTextField(
            label: 'Amount',
            controller: _amount,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter the amount',
          ),
          ChoiceField<String>(label: 'Paid by', options: _methods, value: _method, onChanged: (v) => setState(() => _method = v)),
          if (_method != 'cash')
            AppTextField(label: 'UTR, cheque or transfer reference', controller: _reference, mandatory: true, capitalization: TextCapitalization.characters),
          AppTextField(label: _kind == 'reversal' ? 'Why it is reversed' : 'Note', controller: _note, mandatory: _kind == 'reversal', capitalization: TextCapitalization.sentences),
        ],
      );
}

/// A deduction from the owner's balance, or an office expense on the trip.
class _AmountForm extends StatefulWidget {
  const _AmountForm({required this.tripId, required this.kind});

  final String tripId;

  /// "deductions" or "expenses".
  final String kind;

  @override
  State<_AmountForm> createState() => _AmountFormState();
}

class _AmountFormState extends State<_AmountForm> with Submitter {
  final _amount = TextEditingController();
  final _note = TextEditingController();
  late String _type = widget.kind == 'deductions' ? 'shortage' : 'loading_labour';

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final note = _note.text.trim();
    await context.read<ApiClient>().post('/trips/${widget.tripId}/${widget.kind}', {
      'amount': _amount.text.trim(),
      widget.kind == 'deductions' ? 'reason' : 'kind': _type,
      if (note.isNotEmpty) 'note': note,
    });
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final deduction = widget.kind == 'deductions';
    return FormPage(
      title: deduction ? 'Deduct from the owner' : 'Trip expense',
      subtitle: deduction ? 'Taken off what the truck owner is still owed, for example goods short on arrival.' : 'Paid by the office for this trip, beyond the hire.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Save',
      onSubmit: () => submit(_save),
      children: [
        ChoiceField<String>(
          label: deduction ? 'Reason' : 'Expense',
          options: deduction ? _deductionReasons : _expenseKinds,
          value: _type,
          onChanged: (v) => setState(() => _type = v),
        ),
        AppTextField(
          label: 'Amount',
          controller: _amount,
          mandatory: true,
          unit: 'Rs',
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter the amount',
        ),
        AppTextField(label: 'Note', controller: _note, mandatory: deduction, capitalization: TextCapitalization.sentences),
      ],
    );
  }
}

/// What is owed to truck owners, by owner, oldest first within each.
class PayablesScreen extends StatelessWidget {
  const PayablesScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Owed to truck owners')),
        body: Loader<Map<String, dynamic>>(
          cacheKey: 'payables',
          errorTitle: 'Could not load what is owed',
          load: () async => await context.read<ApiClient>().get('/payables') as Map<String, dynamic>,
          builder: (context, d) {
            final text = Theme.of(context).textTheme;
            final vendors = (d['vendors'] as List).cast<Map<String, dynamic>>();
            final trips = (d['trips'] as List).cast<Map<String, dynamic>>();
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                DarkPanel(child: MetricTile(value: _rs(d['total_owed']), label: 'Owed to truck owners in all', onDark: true)),
                const SizedBox(height: 12),
                if (vendors.isEmpty) const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'All settled', body: 'No truck owner is owed anything.'),
                for (final v in vendors) ...[
                  SectionHeader('${v['vendor_name']} · ${_rs(v['owed'])}', icon: Icons.local_shipping_outlined),
                  for (final t in trips.where((t) => t['vendor_id'] == v['vendor_id']))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: AppCard(
                        onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                          builder: (_) => TripMoneyScreen(tripId: t['trip_id'] as String, title: 'Trip ${t['trip_no']}'),
                        )),
                        padding: const EdgeInsets.all(14),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                'Trip ${t['trip_no']} · ${t['vehicle_number']} · ${t['destination']}\n'
                                'Hire ${_rs(t['hire'])}, paid ${_rs(t['paid_to_owner'])}${t['status'] == 'completed' ? ' · delivered' : ' · on the road'}',
                                style: text.bodySmall,
                              ),
                            ),
                            Text(_rs(t['owed_to_owner']), style: text.labelLarge),
                          ],
                        ),
                      ),
                    ),
                ],
              ],
            );
          },
        ),
      );
}

/// Requests for quotes: ask several truck owners for a price, compare, award.
class RfqsScreen extends StatefulWidget {
  const RfqsScreen({super.key});

  @override
  State<RfqsScreen> createState() => _RfqsScreenState();
}

class _RfqsScreenState extends State<RfqsScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();
  String _status = 'open';

  Future<void> _open(Widget screen) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
    await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Truck quotes')),
        bottomNavigationBar: BottomBar(children: [BusyButton(icon: Icons.add, label: 'Ask for quotes', onPressed: () => _open(const _RfqForm()))]),
        body: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Segmented<String>(
                options: const {'open': 'Open', 'awarded': 'Awarded', 'cancelled': 'Cancelled'},
                value: _status,
                onChanged: (v) {
                  setState(() => _status = v);
                  _loader.currentState?.reload();
                },
              ),
            ),
            Expanded(
              child: Loader<List<dynamic>>(
                key: _loader,
                errorTitle: 'Could not load quotes',
                load: () async => await context.read<ApiClient>().get('/rfqs', query: {'rfq_status': _status}) as List,
                builder: (context, rows) {
                  final text = Theme.of(context).textTheme;
                  final rfqs = rows.cast<Map<String, dynamic>>();
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                    children: [
                      if (rfqs.isEmpty) const MessageView(card: true, icon: Icons.request_quote_outlined, title: 'None here', body: 'Ask truck owners for a price before agreeing a hire.'),
                      for (final r in rfqs)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: AppCard(
                            onTap: () => _open(RfqScreen(rfqId: r['id'] as String)),
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('RFQ-${r['rfq_number']} · ${r['origin']} → ${r['destination']}', style: text.titleMedium),
                                Text(
                                  '${kgLabel(double.parse(r['weight_kg'] as String))} · needed ${dayLabel(r['needed_on'] as String)} · '
                                  '${(r['quotes'] as List).length} of ${(r['invited'] as List).length} quoted'
                                  '${(r['quotes'] as List).isNotEmpty ? ' · best ${_rs((r['quotes'] as List).first['amount'])}' : ''}',
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
            ),
          ],
        ),
      );
}

class _RfqForm extends StatefulWidget {
  const _RfqForm();

  @override
  State<_RfqForm> createState() => _RfqFormState();
}

class _RfqFormState extends State<_RfqForm> with Submitter {
  final _origin = TextEditingController();
  final _destination = TextEditingController();
  final _weight = TextEditingController();
  final _truckType = TextEditingController();
  final _note = TextEditingController();
  DateTime _needed = DateUtils.dateOnly(DateTime.now()).add(const Duration(days: 1));
  final Set<String> _chosen = {};

  @override
  void dispose() {
    for (final c in [_origin, _destination, _weight, _truckType, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (_chosen.isEmpty) throw const ApiException(0, 'Choose at least one truck owner to ask.');
    String? orNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
    final rfq = await context.read<ApiClient>().post('/rfqs', {
      'origin': _origin.text.trim(),
      'destination': _destination.text.trim(),
      'weight_kg': _weight.text.trim(),
      'truck_type': orNull(_truckType),
      'needed_on': _needed.toIso8601String().substring(0, 10),
      'note': orNull(_note),
      'vendor_ids': _chosen.toList(),
    }) as Map<String, dynamic>;
    if (mounted) await Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => RfqScreen(rfqId: rfq['id'] as String)));
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Ask for quotes',
        subtitle: 'Each chosen owner with a phone gets the details by WhatsApp or SMS once a provider is connected.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Send request',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(label: 'From', controller: _origin, mandatory: true, capitalization: TextCapitalization.characters, check: city),
          AppTextField(label: 'To', controller: _destination, mandatory: true, capitalization: TextCapitalization.characters, check: city),
          AppTextField(
            label: 'Load',
            controller: _weight,
            mandatory: true,
            unit: 'kg',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter the weight',
          ),
          AppTextField(label: 'Truck type', controller: _truckType, hint: 'e.g. 32 ft closed body'),
          PickerField(
            label: 'Needed on',
            value: dayLabel(_needed.toIso8601String().substring(0, 10)),
            icon: Icons.calendar_today_outlined,
            onTap: () async {
              final today = DateUtils.dateOnly(DateTime.now());
              final picked = await showDatePicker(context: context, firstDate: today, lastDate: today.add(const Duration(days: 60)), initialDate: _needed);
              if (picked != null) setState(() => _needed = picked);
            }, placeholder: '',
          ),
          AppTextField(label: 'Note', controller: _note, capitalization: TextCapitalization.sentences),
          const SectionHeader('Ask', icon: Icons.local_shipping_outlined),
          FutureBuilder(
            future: context.read<ApiClient>().get('/vendors'),
            builder: (context, snapshot) => Column(
              children: [
                for (final v in ((snapshot.data as List?) ?? const []).cast<Map<String, dynamic>>())
                  if (v['is_active'] as bool)
                    CheckboxListTile(
                      value: _chosen.contains(v['id']),
                      onChanged: (on) => setState(() => on == true ? _chosen.add(v['id'] as String) : _chosen.remove(v['id'])),
                      title: Text(v['name'] as String),
                      subtitle: Text(v['phone'] as String? ?? 'No phone: record their quote by hand'),
                    ),
              ],
            ),
          ),
        ],
      );
}

/// One request: quotes ranked cheapest first, with each owner's earlier prices.
class RfqScreen extends StatefulWidget {
  const RfqScreen({super.key, required this.rfqId});

  final String rfqId;

  @override
  State<RfqScreen> createState() => _RfqScreenState();
}

class _RfqScreenState extends State<RfqScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Future<void> _act(String path, [Map<String, dynamic> body = const {}]) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/rfqs/${widget.rfqId}/$path', body);
      await _loader.currentState?.reload();
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _quote() async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => _QuoteForm(rfqId: widget.rfqId)));
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) => Loader<Map<String, dynamic>>(
        key: _loader,
        errorTitle: 'Could not load the request',
        load: () async => await context.read<ApiClient>().get('/rfqs/${widget.rfqId}') as Map<String, dynamic>,
        builder: (context, r) {
          final text = Theme.of(context).textTheme;
          final open = r['status'] == 'open';
          final quotes = (r['quotes'] as List).cast<Map<String, dynamic>>();
          return Scaffold(
            appBar: AppBar(title: Text('RFQ-${r['rfq_number']}')),
            bottomNavigationBar: open ? BottomBar(children: [BusyButton(icon: Icons.add, label: 'Record a quote', onPressed: _quote)]) : null,
            body: ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                DarkPanel(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${r['origin']} → ${r['destination']}', style: onInk(text.titleLarge!)),
                      Text(
                        '${kgLabel(double.parse(r['weight_kg'] as String))}${r['truck_type'] != null ? ' · ${r['truck_type']}' : ''} · needed ${dayLabel(r['needed_on'] as String)}',
                        style: onInk(text.bodySmall!, muted: true),
                      ),
                    ],
                  ),
                ),
                SectionHeader('Quotes · ${quotes.length}', icon: Icons.request_quote_outlined),
                if (quotes.isEmpty) const PageIntro('No quotes yet.'),
                for (final q in quotes)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text('${q['rank']}. ${q['vendor_name']}', style: text.titleMedium)),
                              Text(_rs(q['amount']), style: text.titleMedium),
                            ],
                          ),
                          Text(
                            [
                              dateTimeLabel(q['received_at'] as String),
                              if (q['vehicle_number'] != null) q['vehicle_number'] as String,
                              if ((q['revisions'] as List).isNotEmpty) 'earlier ${(q['revisions'] as List).map((a) => _rs(a)).join(', ')}',
                            ].join(' · '),
                            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                          ),
                          if (r['awarded_quote_id'] == q['id'])
                            Padding(padding: const EdgeInsets.only(top: 8), child: StatusChip.tone('Awarded', Tone.success)),
                          if (open)
                            Align(
                              alignment: Alignment.centerRight,
                              child: TextButton(onPressed: () => _act('award', {'quote_id': q['id']}), child: const Text('Award')),
                            ),
                        ],
                      ),
                    ),
                  ),
                if ((r['not_responded'] as List).isNotEmpty) ...[
                  SectionHeader('Not quoted yet · ${(r['not_responded'] as List).length}', icon: Icons.hourglass_empty),
                  Text((r['not_responded'] as List).join(', '), style: text.bodyMedium),
                  if (open) Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => _act('remind'), child: const Text('Remind them'))),
                ],
                if (open)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: TextButton(style: TextButton.styleFrom(foregroundColor: Palette.error), onPressed: () => _act('cancel'), child: const Text('Cancel this request')),
                  ),
              ],
            ),
          );
        },
      );
}

class _QuoteForm extends StatefulWidget {
  const _QuoteForm({required this.rfqId});

  final String rfqId;

  @override
  State<_QuoteForm> createState() => _QuoteFormState();
}

class _QuoteFormState extends State<_QuoteForm> with Submitter {
  final _amount = TextEditingController();
  final _vehicle = TextEditingController();
  String? _vendor;

  @override
  void dispose() {
    _amount.dispose();
    _vehicle.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_vendor == null) throw const ApiException(0, 'Choose who quoted.');
    final vehicle = _vehicle.text.trim();
    await context.read<ApiClient>().post('/rfqs/${widget.rfqId}/quotes', {
      'vendor_id': _vendor,
      'amount': _amount.text.trim(),
      if (vehicle.isNotEmpty) 'vehicle_number': vehicle,
    });
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Record a quote',
        subtitle: 'A new price from the same owner replaces their earlier one; both are kept.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save quote',
        onSubmit: () => submit(_save),
        children: [
          FutureBuilder(
            future: context.read<ApiClient>().get('/vendors'),
            builder: (context, snapshot) => ChoiceField<String?>(
              label: 'Truck owner',
              options: {
                null: 'Choose…',
                for (final v in ((snapshot.data as List?) ?? const []).cast<Map<String, dynamic>>())
                  if (v['is_active'] as bool) v['id'] as String: v['name'] as String,
              },
              value: _vendor,
              onChanged: (v) => setState(() => _vendor = v),
            ),
          ),
          AppTextField(
            label: 'Price',
            controller: _amount,
            mandatory: true,
            unit: 'Rs',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            check: (v) => (double.tryParse(v) ?? 0) > 0 ? null : 'Enter the price',
          ),
          AppTextField(label: 'Truck number', controller: _vehicle, capitalization: TextCapitalization.characters),
        ],
      );
}
