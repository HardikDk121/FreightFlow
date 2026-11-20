import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';

String _held(Map<String, dynamic> c) {
  final cheques = c['cheque_count'] as int;
  return '${money(c['cash'] as String)} cash'
      '${cheques == 0 ? '' : ' · $cheques cheque${cheques == 1 ? '' : 's'} ${money(c['cheques'] as String)}'}';
}

/// What the signed-in person is holding, and since when. Shown on the Collections screen.
class MyCustodyCard extends StatelessWidget {
  const MyCustodyCard({super.key, required this.custody});

  final Map<String, dynamic> custody;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final oldest = custody['oldest'] as String?;
    final late = oldest != null && DateTime.now().difference(DateTime.parse(oldest)).inHours >= 24;
    return DarkPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionLabel('You are holding', onDark: true),
          Text(_held(custody), style: onInk(text.titleLarge!)),
          const SizedBox(height: 6),
          Text(
            oldest == null
                ? 'Nothing. Everything you collected has been handed over or banked.'
                : 'Oldest since ${dateTimeLabel(oldest)}. Hand it over or bank it the same day.',
            style: onInk(text.bodySmall!, muted: true).copyWith(color: late ? const Color(0xFFFF8A75) : null),
          ),
        ],
      ),
    );
  }
}

/// Receive a collector's cash and cheques. The app shows what to expect; you enter what you counted.
class HandoverScreen extends StatefulWidget {
  const HandoverScreen({super.key});

  @override
  State<HandoverScreen> createState() => _HandoverScreenState();
}

class _HandoverScreenState extends State<HandoverScreen> with Submitter {
  final _key = newIdempotencyKey();
  Map<String, dynamic>? _from;
  final _counted = TextEditingController();
  final Set<String> _cheques = {};

  @override
  void dispose() {
    _counted.dispose();
    super.dispose();
  }

  void _choose(Map<String, dynamic> person) => setState(() {
        _from = person;
        _counted.clear();
        _cheques.clear();
      });

  Future<void> _receive() async {
    final result = await context.read<ApiClient>().post(idempotencyKey: _key, '/handovers', {
      'from_user_id': _from!['user_id'],
      'counted_cash': _counted.text.trim(),
      'cheque_ids': _cheques.toList(),
    }) as Map<String, dynamic>;
    if (!mounted) return;
    final short = double.parse(result['shortage'] as String) > 0;
    await showDialog<void>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(short ? 'Short by ${money(result['shortage'] as String)}' : 'Handover received'),
        content: Text(
          short
              ? 'Recorded against ${result['from_name']}. The owner will see it and decide.'
              : '${money(result['counted_cash'] as String)} received from ${result['from_name']}, as expected.',
        ),
        actions: [TextButton(onPressed: () => Navigator.of(dialog).pop(), child: const Text('OK'))],
      ),
    );
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final from = _from;
    if (from == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Receive a handover')),
        body: Loader<List<dynamic>>(
          errorTitle: 'Could not load who is holding money',
          load: () async => await context.read<ApiClient>().get('/custody') as List,
          builder: (context, people) {
            final text = Theme.of(context).textTheme;
            final me = context.read<Session>().user?.id;
            final others = [for (final p in people.cast<Map<String, dynamic>>()) if (p['user_id'] != me) p];
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro('Who is handing over? You cannot receive your own collections.'),
                if (others.isEmpty)
                  const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Nobody is holding money', body: 'Every collection has been handed over or banked.'),
                for (final p in others)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      onTap: () => _choose(p),
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(p['name'] as String, style: text.titleMedium),
                                Text(_held(p), style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
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
        ),
      );
    }
    final items = (from['items'] as List).cast<Map<String, dynamic>>();
    final cheques = items.where((i) => i['kind'] == 'cheque').toList();
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'From ${from['name']}',
      subtitle: 'Count the cash before you type. If it is short, the shortage is recorded against them now.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Receive',
      onSubmit: () => submit(_receive),
      children: [
        DarkPanel(
          child: MetricTile(value: money(from['cash'] as String), label: 'Cash the app expects', onDark: true),
        ),
        const SizedBox(height: 16),
        AppTextField(
          label: 'Cash you counted',
          controller: _counted,
          mandatory: true,
          unit: 'Rs',
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          check: (v) {
            final n = double.tryParse(v);
            if (n == null || n < 0) return 'Enter the amount counted';
            return n > double.parse(from['cash'] as String) ? 'More than expected: count again' : null;
          },
        ),
        if (cheques.isNotEmpty) ...[
          Text('Cheques you have in hand', style: text.titleMedium),
          const SizedBox(height: 8),
          for (final c in cheques)
            AppCard(
              child: CheckboxListTile(
                value: _cheques.contains(c['collection_id']),
                onChanged: (on) => setState(() => on == true ? _cheques.add(c['collection_id'] as String) : _cheques.remove(c['collection_id'])),
                title: Text('${money(c['amount'] as String)} · cheque ${c['cheque_number']}'),
                subtitle: Text(c['payer_name'] as String),
              ),
            ),
          const SizedBox(height: 6),
          Text('Cheques you do not tick stay with ${from['name']}.', style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
        ],
      ],
    );
  }
}

/// Bank everything held in cash, and the cheques chosen. The batch number goes on the slip.
class DepositScreen extends StatefulWidget {
  const DepositScreen({super.key});

  @override
  State<DepositScreen> createState() => _DepositScreenState();
}

class _DepositScreenState extends State<DepositScreen> with Submitter {
  final _key = newIdempotencyKey();
  final _cash = TextEditingController();
  final _slip = TextEditingController();
  final Set<String> _cheques = {};
  Map<String, dynamic>? _held;

  @override
  void dispose() {
    _cash.dispose();
    _slip.dispose();
    super.dispose();
  }

  Future<void> _deposit() async {
    final slip = _slip.text.trim();
    final result = await context.read<ApiClient>().post(idempotencyKey: _key, '/deposits', {
      'cash_amount': _cash.text.trim(),
      'cheque_ids': _cheques.toList(),
      if (slip.isNotEmpty) 'slip_reference': slip,
    }) as Map<String, dynamic>;
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text('Write ${result['deposit_number']} on the slip'),
        content: Text(
          'The owner matches this deposit to the bank statement by that number and the amount.'
          '${double.parse(result['shortage'] as String) > 0 ? '\n\nYou held ${money(result['expected_cash'] as String)}: the ${money(result['shortage'] as String)} not banked is recorded as a shortage.' : ''}',
        ),
        actions: [TextButton(onPressed: () => Navigator.of(dialog).pop(), child: const Text('OK'))],
      ),
    );
    if (mounted) Navigator.of(context).pop(true);
  }

  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loadError = null);
    try {
      final custody = await context.read<ApiClient>().get('/custody/me') as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _held = custody;
        _cash.text = custody['cash'] as String;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final held = _held;
    if (held == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Bank deposit')),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                tone: Tone.danger,
                title: 'Could not load what you are holding',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _load,
              ),
      );
    }
    final cheques = (held['items'] as List).cast<Map<String, dynamic>>().where((i) => i['kind'] == 'cheque').toList();
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Bank deposit',
      subtitle: 'Deposit into the company account only.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Record deposit',
      onSubmit: () => submit(_deposit),
      children: [
        MyCustodyCard(custody: held),
        const SizedBox(height: 16),
        AppTextField(
          label: 'Cash deposited',
          controller: _cash,
          mandatory: true,
          unit: 'Rs',
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          check: (v) {
            final n = double.tryParse(v);
            if (n == null || n < 0) return 'Enter the amount deposited';
            return n > double.parse(held['cash'] as String) ? 'You hold ${money(held['cash'] as String)}' : null;
          },
          helper: 'Anything less than you hold is recorded as a shortage against you.',
        ),
        AppTextField(label: 'Slip or reference number', controller: _slip),
        if (cheques.isNotEmpty) ...[
          Text('Cheques in this deposit', style: text.titleMedium),
          const SizedBox(height: 8),
          for (final c in cheques)
            AppCard(
              child: CheckboxListTile(
                value: _cheques.contains(c['collection_id']),
                onChanged: (on) => setState(() => on == true ? _cheques.add(c['collection_id'] as String) : _cheques.remove(c['collection_id'])),
                title: Text('${money(c['amount'] as String)} · cheque ${c['cheque_number']}'),
                subtitle: Text(c['payer_name'] as String),
              ),
            ),
        ],
      ],
    );
  }
}
