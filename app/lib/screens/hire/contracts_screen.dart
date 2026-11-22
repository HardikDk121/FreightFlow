import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';

StatusChip _contractChip(String status, int daysLeft) => switch (status) {
      'active' => StatusChip.tone('Active', Tone.success),
      'expiring' => StatusChip.tone('Ends in $daysLeft days', Tone.warning),
      'expired' => StatusChip.tone('Ended', Tone.danger),
      'upcoming' => StatusChip.tone('Starts later', Tone.info),
      _ => StatusChip.tone('Stopped', Tone.neutral),
    };

/// Customers with their own agreed rates. New LRs for them start from the contract rate.
class ContractsScreen extends StatefulWidget {
  const ContractsScreen({super.key});

  @override
  State<ContractsScreen> createState() => _ContractsScreenState();
}

class _ContractsScreenState extends State<ContractsScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();

  Future<void> _edit([Map<String, dynamic>? contract]) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => _ContractForm(contract: contract)));
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canEdit = context.watch<Session>().user!.can('contracts.manage');
    return Scaffold(
      appBar: AppBar(title: const Text('Customer contracts')),
      bottomNavigationBar: canEdit ? BottomBar(children: [BusyButton(icon: Icons.add, label: 'New contract', onPressed: _edit)]) : null,
      body: Loader<List<dynamic>>(
        key: _loader,
        cacheKey: 'contracts',
        errorTitle: 'Could not load contracts',
        load: () async => await context.read<ApiClient>().get('/contracts') as List,
        builder: (context, rows) {
          final text = Theme.of(context).textTheme;
          final contracts = rows.cast<Map<String, dynamic>>();
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            children: [
              const PageIntro('Agreed rates per destination for a period. Booking an LR for these customers starts from the contract rate; LRs charged differently show up in Analytics.'),
              if (contracts.isEmpty) const MessageView(card: true, icon: Icons.description_outlined, title: 'No contracts', body: 'Every customer is charged at your normal rates.'),
              for (final c in contracts)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: AppCard(
                    onTap: canEdit ? () => _edit(c) : null,
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(child: Text(c['party_name'] as String, style: text.titleMedium)),
                            _contractChip(c['status'] as String, c['days_left'] as int),
                          ],
                        ),
                        Text(
                          '${dayLabel(c['starts_on'] as String)} to ${dayLabel(c['ends_on'] as String)} · '
                          '${(c['rates'] as List).map((r) => '${r['destination']} ₹${r['rate']}/${r['basis'] == 'per_kg' ? 'kg' : 'art'}').join(', ')}',
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

class _RateRow {
  _RateRow({String destination = '', this.basis = 'per_kg', String rate = ''})
      : destination = TextEditingController(text: destination),
        rate = TextEditingController(text: rate);

  final TextEditingController destination;
  final TextEditingController rate;
  String basis;

  void dispose() {
    destination.dispose();
    rate.dispose();
  }
}

class _ContractForm extends StatefulWidget {
  const _ContractForm({this.contract});

  final Map<String, dynamic>? contract;

  @override
  State<_ContractForm> createState() => _ContractFormState();
}

class _ContractFormState extends State<_ContractForm> with Submitter {
  late final _party = TextEditingController(text: widget.contract?['party_name'] as String? ?? '');
  late final _terms = TextEditingController(text: widget.contract?['terms'] as String? ?? '');
  late DateTime _starts = widget.contract == null ? DateUtils.dateOnly(DateTime.now()) : DateTime.parse(widget.contract!['starts_on'] as String);
  late DateTime _ends = widget.contract == null ? DateTime(DateTime.now().year, DateTime.now().month + 6, DateTime.now().day) : DateTime.parse(widget.contract!['ends_on'] as String);
  late bool _active = widget.contract?['is_active'] as bool? ?? true;
  late final List<_RateRow> _rates = [
    for (final r in ((widget.contract?['rates'] as List?) ?? const []).cast<Map<String, dynamic>>())
      _RateRow(destination: r['destination'] as String, basis: r['basis'] as String, rate: r['rate'] as String),
    if (widget.contract == null) _RateRow(),
  ];

  @override
  void dispose() {
    _party.dispose();
    _terms.dispose();
    for (final r in _rates) {
      r.dispose();
    }
    super.dispose();
  }

  Future<void> _pick(bool start) async {
    final picked = await showDatePicker(context: context, firstDate: DateTime(2024), lastDate: DateTime(2035), initialDate: start ? _starts : _ends);
    if (picked != null) setState(() => start ? _starts = picked : _ends = picked);
  }

  Future<void> _save() async {
    final terms = _terms.text.trim();
    final body = {
      'party_name': _party.text.trim(),
      'starts_on': _starts.toIso8601String().substring(0, 10),
      'ends_on': _ends.toIso8601String().substring(0, 10),
      'terms': terms.isEmpty ? null : terms,
      'is_active': _active,
      'rates': [
        for (final r in _rates)
          if (r.destination.text.trim().isNotEmpty) {'destination': r.destination.text.trim(), 'basis': r.basis, 'rate': r.rate.text.trim()},
      ],
    };
    final api = context.read<ApiClient>();
    final contract = widget.contract;
    if (contract == null) {
      await api.post('/contracts', body);
    } else {
      await api.put('/contracts/${contract['id']}', body);
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
    title: widget.contract == null ? 'New contract' : 'Edit contract',
    formKey: formKey,
    busy: busy,
    error: error,
    submitLabel: 'Save contract',
    onSubmit: () => submit(_save),
    children: [
      AppTextField(label: 'Customer (who pays)', controller: _party, mandatory: true, minLength: 2, capitalization: TextCapitalization.words),
      Row(
        children: [
          Expanded(
            child: PickerField(
              label: 'From',
              placeholder: 'Select start date',
              value: dayLabel(_starts.toIso8601String().substring(0, 10)),
              icon: Icons.calendar_today_outlined,
              onTap: () => _pick(true),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: PickerField(
              label: 'To',
              placeholder: 'Select end date',
              value: dayLabel(_ends.toIso8601String().substring(0, 10)),
              icon: Icons.calendar_today_outlined,
              onTap: () => _pick(false),
            ),
          ),
        ],
      ),
      const SectionHeader('Agreed rates', icon: Icons.currency_rupee),
      for (final r in _rates)
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(flex: 3, child: AppTextField(label: 'Destination', controller: r.destination, capitalization: TextCapitalization.characters)),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: ChoiceField<String>(label: 'Per', options: const {'per_kg': 'kg', 'per_article': 'article'}, value: r.basis, onChanged: (v) => setState(() => r.basis = v)),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: AppTextField(
                label: 'Rate',
                controller: r.rate,
                unit: 'Rs',
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                check: (v) => r.destination.text.trim().isEmpty || (double.tryParse(v) ?? 0) > 0 ? null : 'Rate',
              ),
            ),
          ],
        ),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(icon: const Icon(Icons.add), label: const Text('Another destination'), onPressed: () => setState(() => _rates.add(_RateRow()))),
      ),
      AppTextField(label: 'Terms', controller: _terms, lines: 3, capitalization: TextCapitalization.sentences, helper: 'Anything else agreed: billing cycle, minimum load, who pays hamali.'),
      if (widget.contract != null) SwitchField(label: 'In force', value: _active, onChanged: (v) => setState(() => _active = v)),
    ],
  );
}

/// What the office tells customers each destination usually takes. Used to judge late trips; not a promise.
class TransitTimesScreen extends StatefulWidget {
  const TransitTimesScreen({super.key});

  @override
  State<TransitTimesScreen> createState() => _TransitTimesScreenState();
}

class _TransitTimesScreenState extends State<TransitTimesScreen> with Submitter {
  final List<(TextEditingController, TextEditingController, TextEditingController)> _rows = [];
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final rows = (await context.read<ApiClient>().get('/transit-times') as List).cast<Map<String, dynamic>>();
    if (!mounted) return;
    setState(() {
      for (final r in rows) {
        _rows.add((TextEditingController(text: r['destination'] as String), TextEditingController(text: '${r['days_min']}'), TextEditingController(text: '${r['days_max']}')));
      }
      if (_rows.isEmpty) _rows.add((TextEditingController(), TextEditingController(), TextEditingController()));
      _loaded = true;
    });
  }

  @override
  void dispose() {
    for (final (a, b, c) in _rows) {
      a.dispose();
      b.dispose();
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    await context.read<ApiClient>().put('/transit-times', [
      for (final (dest, min, max) in _rows)
        if (dest.text.trim().isNotEmpty) {'destination': dest.text.trim(), 'days_min': int.parse(min.text.trim()), 'days_max': int.parse(max.text.trim())},
    ]);
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Usual transit times',
        subtitle: 'What you tell customers, for example Raipur 4 to 5 days. A trip on the road longer than the longest is shown as late.',
        formKey: formKey,
        busy: busy || !_loaded,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          for (final (dest, min, max) in _rows)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 3, child: AppTextField(label: 'Destination', controller: dest, capitalization: TextCapitalization.characters)),
                const SizedBox(width: 8),
                Expanded(flex: 2, child: AppTextField(label: 'From', controller: min, unit: 'days', keyboardType: TextInputType.number, check: (v) => dest.text.trim().isEmpty || (int.tryParse(v) ?? 0) > 0 ? null : 'Days')),
                const SizedBox(width: 8),
                Expanded(flex: 2, child: AppTextField(label: 'To', controller: max, unit: 'days', keyboardType: TextInputType.number, check: (v) => dest.text.trim().isEmpty || (int.tryParse(v) ?? 0) >= (int.tryParse(min.text) ?? 0) ? null : 'Days')),
              ],
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Another destination'),
              onPressed: () => setState(() => _rows.add((TextEditingController(), TextEditingController(), TextEditingController()))),
            ),
          ),
        ],
      );
}
