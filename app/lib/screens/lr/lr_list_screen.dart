import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/pdf_screen.dart';
import '../payments/payments_screens.dart';
import '../shell.dart';
import 'lr_form_screen.dart';
import 'lr_page.dart';

String _iso(DateTime d) => d.toIso8601String().substring(0, 10);

/// The e-way bill state of an LR as a pill, or null when there is nothing worth showing.
StatusChip? ewbChip(String status) => switch (status) {
      'active' => StatusChip.tone('EWB valid', Tone.success),
      'awaiting_part_b' => StatusChip.tone('EWB ready', Tone.info),
      'pending' => StatusChip.tone('EWB missing', Tone.danger),
      'exempt' => StatusChip.tone('EWB exempt', Tone.neutral),
      _ => null,
    };

/// Saved LRs for a period, newest first, with search, the period's total and the register PDF.
class LrListScreen extends StatefulWidget {
  const LrListScreen({super.key});

  @override
  State<LrListScreen> createState() => _LrListScreenState();
}

class _LrListScreenState extends State<LrListScreen> {
  static const _pageSize = 200;

  final _search = TextEditingController();
  Timer? _debounce;
  late DateTimeRange _range = _thisMonth();
  List<Map<String, dynamic>>? _lrs;
  String? _error;
  int _request = 0;

  static DateTimeRange _thisMonth() {
    final now = DateUtils.dateOnly(DateTime.now());
    return DateTimeRange(start: DateTime(now.year, now.month), end: now);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final request = ++_request;
    setState(() {
      _lrs = null;
      _error = null;
    });
    final q = _search.text.trim();
    try {
      final data = await context.read<ApiClient>().get('/lrs', query: {
        'limit': '$_pageSize',
        'date_from': _iso(_range.start),
        'date_to': _iso(_range.end),
        if (q.isNotEmpty) 'q': q,
      });
      if (!mounted || request != _request) return;
      setState(() => _lrs = (data as List).cast<Map<String, dynamic>>());
    } on ApiException catch (e) {
      if (!mounted || request != _request) return;
      setState(() => _error = e.message);
    }
  }

  /// Open a screen and refresh on return: an LR may have been booked, cancelled or given its e-way bill.
  Future<void> _open(Widget screen) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => screen));
    if (mounted) await _load();
  }

  Future<void> _pickRange() async {
    final now = DateTime.now();
    final range = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2020),
      lastDate: now,
      initialDateRange: _range,
      helpText: 'RECEIPT PERIOD',
      saveText: 'Save',
    );
    if (range == null || !mounted) return;
    setState(() => _range = range);
    await _load();
  }

  /// Every LR booked in the chosen period, as a printable register.
  void _openRegister() => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PdfScreen(
            title: 'LR register',
            path: '/lrs/register.pdf?date_from=${_iso(_range.start)}&date_to=${_iso(_range.end)}',
            fileName: 'LR-register-${_iso(_range.start)}-to-${_iso(_range.end)}.pdf',
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final canBook = context.select<Session, bool>((s) => s.user?.canBookLr ?? false);
    final text = Theme.of(context).textTheme;
    final lrs = _lrs;
    final live = lrs?.where((lr) => lr['status'] == 'confirmed') ?? const [];
    final total = live.fold<double>(0, (sum, lr) => sum + double.parse(lr['total'] as String));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Lorry receipts'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: Palette.ink,
                foregroundColor: Palette.onInk,
                minimumSize: const Size(0, 40),
                padding: const EdgeInsets.symmetric(horizontal: 16),
              ),
              onPressed: _openRegister,
              icon: const Icon(Icons.download, size: 18),
              label: const Text('PDF'),
            ),
          ),
        ],
      ),
      floatingActionButton: canBook
          ? Padding(
              padding: const EdgeInsets.only(bottom: navBarClearance - 24),
              child: FloatingActionButton.extended(
                heroTag: 'new-lr',
                onPressed: () => _open(const LrFormScreen()),
                icon: const Icon(Icons.add),
                label: const Text('New LR'),
              ),
            )
          : null,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
            child: TextField(
              controller: _search,
              onChanged: (_) {
                _debounce?.cancel();
                _debounce = Timer(const Duration(milliseconds: 350), _load);
              },
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: 'Search LR number or party',
                prefixIcon: const Icon(Icons.search),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                enabledBorder:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Row(
              children: [
                ActionChip(
                  backgroundColor: Palette.ink,
                  side: BorderSide.none,
                  label: Text('${rangeLabel(_range.start, _range.end)}  ▾'),
                  labelStyle: text.labelMedium!.copyWith(color: Palette.onInk),
                  onPressed: _pickRange,
                ),
                const Spacer(),
                if (lrs != null)
                  Flexible(
                    child: Text(
                      '${lrs.length >= _pageSize ? '$_pageSize+' : lrs.length} receipt${lrs.length == 1 ? '' : 's'}'
                      ' · ${rupees(total)}',
                      overflow: TextOverflow.ellipsis,
                      style: text.labelMedium!.copyWith(color: Palette.onSurfaceMuted),
                    ),
                  ),
              ],
            ),
          ),
          Expanded(child: _body(canBook)),
        ],
      ),
    );
  }

  Widget _body(bool canBook) {
    if (_error != null) {
      return MessageView(
        icon: Icons.cloud_off_outlined,
        title: 'Could not load receipts',
        body: _error!,
        actionLabel: 'Try again',
        onAction: _load,
        tone: Tone.danger,
      );
    }
    final lrs = _lrs;
    if (lrs == null) return const SkeletonList();
    if (lrs.isEmpty) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, navBarClearance),
        children: [
          MessageView(
            card: true,
            icon: Icons.receipt_long_outlined,
            title: _search.text.trim().isEmpty ? 'No receipts in this period' : 'No matching receipts',
            body: canBook ? 'Book one with New LR, or choose another period.' : 'Choose another period.',
          ),
        ],
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, navBarClearance + 64),
        itemCount: lrs.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, i) => LrCard(lr: lrs[i], onTap: () => _open(LrDetailScreen(lr: lrs[i]))),
      ),
    );
  }
}

/// One LR in a list: number and amount, route, parties, and a line of facts.
class LrCard extends StatelessWidget {
  const LrCard({super.key, required this.lr, required this.onTap});

  final Map<String, dynamic> lr;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final muted = text.bodySmall!.copyWith(color: Palette.onSurfaceMuted);
    final cancelled = lr['status'] == 'cancelled';
    final weight = lr['weight'] as String?;
    final ewb = cancelled ? null : ewbChip(lr['ewb_status'] as String);
    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(lr['lr_number'] as String, style: text.titleLarge)),
              cancelled
                  ? StatusChip.tone('Cancelled', Tone.danger)
                  : StatusChip.tone(rupees(double.parse(lr['total'] as String)), Tone.info),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            '${(lr['from_city'] as String).toUpperCase()} → ${(lr['to_city'] as String).toUpperCase()}',
            style: text.labelLarge,
          ),
          const SizedBox(height: 2),
          Text('${lr['consignor_name']} → ${lr['consignee_name']}', style: text.bodyMedium),
          const SizedBox(height: 8),
          Text(
            [
              '${lr['packages']} pkgs',
              if (weight != null) kgLabel(double.parse(weight)),
              lr['freight_by'] as String,
            ].join(' · '),
            style: muted,
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              if (ewb != null) ewb,
              const Spacer(),
              Text(dayLabel(lr['lr_date'] as String), style: muted),
            ],
          ),
        ],
      ),
    );
  }
}

const _copyOptions = {
  'consignee': 'Consignee',
  'office': 'Office',
  'driver1': 'Driver 1',
  'driver2': 'Driver 2',
};

/// One saved LR: its headline, e-way bill, payments, copies to print, and cancel for admins and managers.
class LrDetailScreen extends StatefulWidget {
  const LrDetailScreen({super.key, required this.lr});

  final Map<String, dynamic> lr;

  @override
  State<LrDetailScreen> createState() => _LrDetailScreenState();
}

class _LrDetailScreenState extends State<LrDetailScreen> {
  /// Which paper copy to show, print or share: 'all' or a key of [_copyOptions].
  String _copy = 'all';

  /// The LR as last read from the server; replaced when the e-way bill number is added.
  late Map<String, dynamic> _lr = widget.lr;
  final _ewayNumber = TextEditingController();
  bool _savingEway = false;

  String get _number => _lr['lr_number'] as String;

  bool get _cancelled => _lr['status'] == 'cancelled';

  @override
  void dispose() {
    _ewayNumber.dispose();
    super.dispose();
  }

  Future<void> _addEwayBill() async {
    final number = _ewayNumber.text.trim();
    final messenger = ScaffoldMessenger.of(context);
    if (!RegExp(r'^[0-9]{12}$').hasMatch(number)) {
      messenger.showSnackBar(const SnackBar(content: Text('An e-way bill number has 12 digits.')));
      return;
    }
    setState(() => _savingEway = true);
    try {
      final updated = await context.read<ApiClient>().patch('/lrs/${_lr['id']}/eway-bill', {'eway_bill_no': number});
      if (!mounted) return;
      setState(() => _lr = updated as Map<String, dynamic>);
      messenger.showSnackBar(SnackBar(content: Text('E-way bill added to $_number.')));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _savingEway = false);
    }
  }

  Future<void> _cancel() async {
    final reason = await showDialog<String>(context: context, builder: (_) => const _CancelDialog());
    if (reason == null || !mounted) return;
    try {
      await context.read<ApiClient>().post('/lrs/${_lr['id']}/cancel', {'reason': reason});
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('LR $_number cancelled.')));
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  void _openPdf() => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PdfScreen(
            title: 'LR $_number',
            path: '/lrs/${_lr['id']}/pdf?copy=$_copy',
            fileName: _copy == 'all' ? 'LR-$_number.pdf' : 'LR-$_number-$_copy.pdf',
            pageFormat: lrPageFormat,
          ),
        ),
      );

  Widget _headline() {
    final text = Theme.of(context).textTheme;
    final weight = _lr['weight'] as String?;
    return DarkPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_number, style: onInk(text.displaySmall!)),
          const SizedBox(height: 4),
          Text('${dayLabel(_lr['lr_date'] as String)} · ${_lr['freight_by']}', style: onInk(text.bodySmall!, muted: true)),
          const SizedBox(height: 16),
          Text(
            '${(_lr['from_city'] as String).toUpperCase()} → ${(_lr['to_city'] as String).toUpperCase()}',
            style: text.titleLarge!.copyWith(color: Palette.primary),
          ),
          const SizedBox(height: 6),
          Text(_lr['consignor_name'] as String, style: onInk(text.labelLarge!)),
          Text('to ${_lr['consignee_name']}', style: onInk(text.bodyMedium!, muted: true)),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Text(
                  [
                    '${_lr['packages']} pkgs',
                    if (weight != null) kgLabel(double.parse(weight)),
                    _lr['goods_description'] as String,
                  ].join(' · '),
                  style: onInk(text.bodyMedium!, muted: true),
                ),
              ),
              Text(rupees(double.parse(_lr['total'] as String)), style: onInk(text.titleLarge!)),
            ],
          ),
        ],
      ),
    );
  }

  /// What the e-way bill rules decided for this LR, how far the bill has got, and adding the number.
  Widget _ewayCard() {
    final text = Theme.of(context).textTheme;
    final status = _lr['ewb_status'] as String;
    final validUntil = _lr['ewb_valid_until'] as String?;
    final (label, tone) = switch (status) {
      'pending' => ('E-way bill needed', Tone.danger),
      'awaiting_part_b' => ('E-way bill ready, waiting for the truck', Tone.info),
      'active' => ('E-way bill valid', Tone.success),
      'exempt' => ('Exempt from e-way bill', Tone.neutral),
      'not_required' => ('No e-way bill needed', Tone.success),
      _ => ('E-way bill not assessed', Tone.neutral),
    };
    final muted = text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted);
    return AppCard(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StatusChip.tone(label, tone),
          if (_lr['ewb_reason'] != null) ...[const SizedBox(height: 10), Text(_lr['ewb_reason'] as String, style: muted)],
          if (_lr['ewb_responsible'] != null && status == 'pending')
            Text('To be generated by the ${_lr['ewb_responsible']}.', style: muted),
          if (_lr['eway_bill_no'] != null) ...[
            const SizedBox(height: 8),
            Text('No. ${_lr['eway_bill_no']}', style: text.titleMedium),
          ],
          if (validUntil != null)
            Text('On truck ${_lr['ewb_vehicle_number']} · valid until ${dateTimeLabel(validUntil)}', style: muted),
          if (status == 'pending') ...[
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _ewayNumber,
                    keyboardType: TextInputType.number,
                    maxLength: 12,
                    decoration: const InputDecoration(hintText: 'Enter 12-digit number', counterText: ''),
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(
                  width: 96,
                  child: BusyButton(label: 'Add', busy: _savingEway, onPressed: _addEwayBill),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _copies() {
    final text = Theme.of(context).textTheme;
    Widget option(String key, String label) {
      final selected = _copy == key;
      return Material(
        color: selected ? Palette.ink : Palette.surface,
        shape: StadiumBorder(side: BorderSide(color: selected ? Palette.ink : Palette.outline)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => setState(() => _copy = key),
          child: SizedBox(
            height: 44,
            child: Center(
              child: Text(
                selected ? '$label · Selected' : label,
                style: text.labelMedium!.copyWith(color: selected ? Palette.onInk : Palette.onSurface),
              ),
            ),
          ),
        ),
      );
    }

    final keys = _copyOptions.keys.toList();
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        children: [
          option('all', 'All 4 copies'),
          const SizedBox(height: 10),
          for (var i = 0; i < keys.length; i += 2) ...[
            if (i > 0) const SizedBox(height: 10),
            Row(
              children: [
                Expanded(child: option(keys[i], _copyOptions[keys[i]]!)),
                const SizedBox(width: 10),
                Expanded(child: option(keys[i + 1], _copyOptions[keys[i + 1]]!)),
              ],
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final canCancel = context.select<Session, bool>((s) => s.user?.canCancelLr ?? false);
    final text = Theme.of(context).textTheme;
    final ewb = _cancelled ? null : ewbChip(_lr['ewb_status'] as String);
    return Scaffold(
      appBar: AppBar(
        title: const Text('LR detail'),
        actions: [
          if (_cancelled)
            Padding(padding: const EdgeInsets.only(right: 16), child: StatusChip.tone('Cancelled', Tone.danger))
          else if (ewb != null)
            Padding(padding: const EdgeInsets.only(right: 16), child: ewb),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
        children: [
          _headline(),
          const SizedBox(height: 12),
          if (_cancelled)
            MessageView(
              card: true,
              icon: Icons.block,
              tone: Tone.danger,
              title: 'This LR is cancelled',
              body: 'Reason: ${_lr['cancel_reason']}\nCancelled LRs cannot be printed.',
            )
          else ...[
            _ewayCard(),
            const SizedBox(height: 12),
            AppCard(
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => LrAccountScreen(lrId: _lr['id'] as String, lrNumber: _number)),
              ),
              child: const ListTile(
                contentPadding: EdgeInsets.symmetric(horizontal: 18, vertical: 4),
                leading: Icon(Icons.account_balance_wallet_outlined, color: Palette.onSurface),
                title: Text('Payments'),
                subtitle: Text('Balance, advances and receipts'),
                trailing: Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
              ),
            ),
            const SectionHeader('Print copies', icon: Icons.print_outlined),
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                'Choose all four or a single copy.',
                style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
              ),
            ),
            _copies(),
            if (canCancel) ...[
              const SizedBox(height: 12),
              AppCard(
                padding: const EdgeInsets.all(18),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('ADMIN ONLY', style: text.labelSmall!.copyWith(color: Palette.error)),
                          const SizedBox(height: 2),
                          Text('Cancel this receipt', style: text.titleMedium),
                        ],
                      ),
                    ),
                    FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: Palette.danger,
                        foregroundColor: Palette.onInk,
                        minimumSize: const Size(0, 44),
                        padding: const EdgeInsets.symmetric(horizontal: 20),
                      ),
                      onPressed: _cancel,
                      child: const Text('Cancel LR'),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ],
      ),
      bottomNavigationBar: _cancelled
          ? null
          : BottomBar(
              children: [
                BusyButton(
                  icon: Icons.picture_as_pdf_outlined,
                  label: _copy == 'all' ? 'Open PDF · All 4 copies' : 'Open PDF · ${_copyOptions[_copy]} copy',
                  onPressed: _openPdf,
                ),
              ],
            ),
    );
  }
}

class _CancelDialog extends StatefulWidget {
  const _CancelDialog();

  @override
  State<_CancelDialog> createState() => _CancelDialogState();
}

class _CancelDialogState extends State<_CancelDialog> {
  final _reason = TextEditingController();

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Cancel this LR?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('The number stays used and the LR stays on record. Give a reason.'),
            const SizedBox(height: 16),
            TextField(
              controller: _reason,
              autofocus: true,
              maxLength: 200,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(hintText: 'For example: wrong consignee'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Keep it')),
          TextButton(
            onPressed: _reason.text.trim().isEmpty ? null : () => Navigator.of(context).pop(_reason.text.trim()),
            style: TextButton.styleFrom(foregroundColor: Palette.error),
            child: const Text('Cancel LR'),
          ),
        ],
      );
}
