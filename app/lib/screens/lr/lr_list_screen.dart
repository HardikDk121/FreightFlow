import 'dart:async';

import 'package:flutter/material.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'lr_form_screen.dart';
import 'lr_page.dart';

/// Saved LRs, newest first, with search. New LRs start here.
class LrListScreen extends StatefulWidget {
  const LrListScreen({super.key});

  @override
  State<LrListScreen> createState() => _LrListScreenState();
}

class _LrListScreenState extends State<LrListScreen> {
  final _search = TextEditingController();
  Timer? _debounce;
  List<Map<String, dynamic>>? _lrs;
  String? _error;
  int _request = 0;

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
      final data = await context.read<ApiClient>().get('/lrs', query: {'limit': '100', if (q.isNotEmpty) 'q': q});
      if (!mounted || request != _request) return;
      setState(() => _lrs = (data as List).cast<Map<String, dynamic>>());
    } on ApiException catch (e) {
      if (!mounted || request != _request) return;
      setState(() => _error = e.message);
    }
  }

  Future<void> _open(Widget screen) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => screen));
    if (changed == true && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final canBook = context.select<Session, bool>((s) => s.user?.canBookLr ?? false);
    return Scaffold(
      appBar: AppBar(title: const Text('LRs')),
      floatingActionButton: canBook
          ? FloatingActionButton.extended(
              heroTag: 'new-lr',
              onPressed: () => _open(const LrFormScreen()),
              icon: const Icon(Icons.add),
              label: const Text('New LR'),
            )
          : null,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: TextField(
              controller: _search,
              onChanged: (_) {
                _debounce?.cancel();
                _debounce = Timer(const Duration(milliseconds: 350), _load);
              },
              textInputAction: TextInputAction.search,
              decoration: const InputDecoration(
                hintText: 'Search LR number or party',
                prefixIcon: Icon(Icons.search),
              ),
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
        title: 'Could not load LRs',
        body: _error!,
        actionLabel: 'Try again',
        onAction: _load,
      );
    }
    final lrs = _lrs;
    if (lrs == null) return const SkeletonList();
    if (lrs.isEmpty) {
      return MessageView(
        icon: Icons.receipt_long_outlined,
        title: _search.text.trim().isEmpty ? 'No LRs yet' : 'No matching LRs',
        body: canBook ? 'Create one with the New LR button.' : 'LRs appear here once they are printed.',
      );
    }
    final text = Theme.of(context).textTheme;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
        itemCount: lrs.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, i) {
          final lr = lrs[i];
          final cancelled = lr['status'] == 'cancelled';
          final weight = lr['weight'] as String?;
          return AppCard(
            child: InkWell(
              onTap: () => _open(LrDetailScreen(lr: lr)),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(lr['lr_number'] as String, style: text.titleMedium)),
                        cancelled
                            ? const StatusChip(
                                'Cancelled',
                                background: Palette.errorContainer,
                                foreground: Palette.error,
                              )
                            : StatusChip(
                                'Rs ${lr['total']}',
                                background: Palette.primaryContainer,
                                foreground: Palette.onPrimaryContainer,
                              ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '${(lr['from_city'] as String).toUpperCase()} → ${(lr['to_city'] as String).toUpperCase()}',
                      style: text.labelMedium,
                    ),
                    const SizedBox(height: 4),
                    Text('${lr['consignor_name']} → ${lr['consignee_name']}', style: text.bodyMedium),
                    const SizedBox(height: 8),
                    Text(
                      [
                        '${lr['packages']} packages',
                        if (weight != null) '${double.parse(weight).toStringAsFixed(0)} kg',
                        lr['freight_by'] as String,
                        lrDateLabel(lr['lr_date'] as String),
                      ].join(' · '),
                      style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

/// One saved LR: the printed form with print and share, and cancel for admins and managers.
/// Pops with `true` if the LR was cancelled.
class LrDetailScreen extends StatefulWidget {
  const LrDetailScreen({super.key, required this.lr});

  final Map<String, dynamic> lr;

  @override
  State<LrDetailScreen> createState() => _LrDetailScreenState();
}

class _LrDetailScreenState extends State<LrDetailScreen> {
  String get _number => widget.lr['lr_number'] as String;

  bool get _cancelled => widget.lr['status'] == 'cancelled';

  Future<void> _cancel() async {
    final reason = await showDialog<String>(context: context, builder: (_) => const _CancelDialog());
    if (reason == null || !mounted) return;
    try {
      await context.read<ApiClient>().post('/lrs/${widget.lr['id']}/cancel', {'reason': reason});
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('LR $_number cancelled.')));
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final canCancel = context.select<Session, bool>((s) => s.user?.canCancelLr ?? false);
    return Scaffold(
      appBar: AppBar(
        title: Text('LR $_number'),
        actions: [
          if (canCancel && !_cancelled)
            TextButton(
              onPressed: _cancel,
              style: TextButton.styleFrom(foregroundColor: Palette.error),
              child: const Text('Cancel LR'),
            ),
        ],
      ),
      body: _cancelled
          ? MessageView(
              icon: Icons.block,
              title: 'This LR is cancelled',
              body: 'Reason: ${widget.lr['cancel_reason']}\nCancelled LRs cannot be printed.',
            )
          : PdfPreview(
              build: (_) => context.read<ApiClient>().getBytes('/lrs/${widget.lr['id']}/pdf'),
              initialPageFormat: lrPageFormat,
              canChangePageFormat: false,
              canChangeOrientation: false,
              canDebug: false,
              pdfFileName: 'LR-$_number.pdf',
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
