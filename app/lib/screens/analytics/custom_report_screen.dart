import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/charts.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/pdf_screen.dart';
import 'analytics_screen.dart' show shareSpreadsheet;

const _lrGroups = {
  'none': 'No grouping (list LRs)', 'payer': 'Customer (payer)', 'consignor': 'Consignor', 'consignee': 'Consignee',
  'origin': 'From', 'destination': 'To', 'lane': 'Route', 'freight_by': 'Freight by', 'charge_basis': 'Charged by',
  'stage': 'Stage', 'day': 'Day', 'week': 'Week', 'month': 'Month',
};
const _lrMeasures = {
  'lrs': 'LRs', 'revenue': 'Revenue', 'freight': 'Freight', 'paid': 'Paid', 'balance': 'Balance', 'packages': 'Packages',
  'weight': 'Weight', 'revenue_per_kg': 'Revenue per kg', 'median_days_to_delivery': 'Days to signature',
};
const _collectionGroups = {'none': 'All together', 'method': 'Method', 'status': 'Status', 'payer': 'Customer', 'day': 'Day', 'week': 'Week', 'month': 'Month'};
const _collectionMeasures = {'collections': 'Payments', 'amount': 'Amount'};

/// Pick what to group by and what to measure, run it over the current filters, export or save it.
class CustomReportScreen extends StatefulWidget {
  const CustomReportScreen({super.key, required this.filters, this.saved});

  /// The analytics filters in force (query parameters).
  final Map<String, String> filters;

  /// Open a saved report to run or change it.
  final Map<String, dynamic>? saved;

  @override
  State<CustomReportScreen> createState() => _CustomReportScreenState();
}

class _CustomReportScreenState extends State<CustomReportScreen> {
  late String _dataset = (widget.saved?['custom']?['dataset'] as String?) ?? 'lrs';
  late String _group = (widget.saved?['custom']?['group_by'] as String?) ?? 'payer';
  late final Set<String> _measures = {...((widget.saved?['custom']?['measures'] as List?)?.cast<String>() ?? const ['lrs', 'revenue', 'weight'])};
  Map<String, dynamic>? _table;
  String? _error;
  bool _busy = false;

  Map<String, String> get _groups => _dataset == 'lrs' ? _lrGroups : _collectionGroups;
  Map<String, String> get _measureOptions => _dataset == 'lrs' ? _lrMeasures : _collectionMeasures;

  Map<String, dynamic> get _definition => {
        'dataset': _dataset,
        'group_by': _group,
        'measures': [for (final m in _measureOptions.keys) if (_measures.contains(m)) m],
        if (_measures.isNotEmpty && _group != 'none') 'sort_by': _measureOptions[_measureOptions.keys.firstWhere(_measures.contains)],
      };

  String get _query => Uri(queryParameters: widget.filters).query;

  Future<void> _run() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final table = await context.read<ApiClient>().post('/analytics/custom?$_query', _definition) as Map<String, dynamic>;
      if (mounted) setState(() => _table = table);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _export(String format) async {
    final api = context.read<ApiClient>();
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await api.postForBytes('/analytics/custom/export?$_query&format=$format', _definition);
      if (format == 'xlsx') {
        await shareSpreadsheet(bytes, 'report.xlsx');
      } else if (mounted) {
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => PdfScreen(title: 'Report', bytes: bytes, fileName: 'report.pdf')));
      }
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _save() async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => SaveReportScreen(analysis: 'custom', custom: _definition, period: widget.filters['period'], existing: widget.saved)),
    );
    if (saved == true && mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Report saved.')));
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final table = _table;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Build a report'),
        actions: [
          IconButton(tooltip: 'Save or schedule', icon: const Icon(Icons.bookmark_add_outlined), onPressed: _save),
          PopupMenuButton<String>(
            tooltip: 'Export',
            icon: const Icon(Icons.ios_share),
            onSelected: _export,
            itemBuilder: (_) => const [PopupMenuItem(value: 'xlsx', child: Text('Excel')), PopupMenuItem(value: 'pdf', child: Text('PDF'))],
          ),
        ],
      ),
      bottomNavigationBar: BottomBar(children: [BusyButton(icon: Icons.play_arrow, label: _busy ? 'Running…' : 'Run report', onPressed: _busy ? null : _run)]),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        children: [
          Segmented<String>(
            options: const {'lrs': 'LRs', 'collections': 'Payments'},
            value: _dataset,
            onChanged: (v) => setState(() {
              _dataset = v;
              _group = v == 'lrs' ? 'payer' : 'method';
              _measures
                ..clear()
                ..addAll(v == 'lrs' ? const ['lrs', 'revenue'] : const ['collections', 'amount']);
              _table = null;
            }),
          ),
          const SizedBox(height: 16),
          ChoiceField<String>(label: 'Group by', options: _groups, value: _group, onChanged: (v) => setState(() => _group = v)),
          if (_group != 'none' || _dataset == 'collections') ...[
            Text('Measures', style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final m in _measureOptions.entries)
                  FilterChip(
                    label: Text(m.value),
                    selected: _measures.contains(m.key),
                    onSelected: (on) => setState(() => on ? _measures.add(m.key) : _measures.remove(m.key)),
                  ),
              ],
            ),
          ],
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 16), child: ErrorBanner(_error!)),
          if (table != null) ...[
            SectionHeader('${table['title']} · ${(table['rows'] as List).length} rows', icon: Icons.table_chart_outlined),
            DataGrid(
              columns: (table['columns'] as List).cast<String>(),
              rows: [
                for (final r in (table['rows'] as List).cast<List>())
                  [for (final cell in r) cell is double ? cell.toStringAsFixed(2) : '${cell ?? '-'}'],
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(table['basis'] as String, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
            ),
          ],
        ],
      ),
    );
  }
}

const _schedules = {'none': 'Not scheduled', 'daily': 'Every morning', 'weekly': 'Mondays', 'monthly': 'On the 1st'};
const _periodLabels = {
  'yesterday': 'Yesterday', 'last_7_days': 'Last 7 days', 'last_30_days': 'Last 30 days', 'this_month': 'This month',
  'last_month': 'Last month', 'this_quarter': 'This quarter', 'last_quarter': 'Last quarter', 'this_year': 'This year', 'last_year': 'Last year',
};

/// Save a report with a named period, and optionally email it as Excel on a schedule.
class SaveReportScreen extends StatefulWidget {
  const SaveReportScreen({super.key, required this.analysis, this.custom, this.period, this.existing});

  final String analysis;
  final Map<String, dynamic>? custom;
  final String? period;
  final Map<String, dynamic>? existing;

  @override
  State<SaveReportScreen> createState() => _SaveReportScreenState();
}

class _SaveReportScreenState extends State<SaveReportScreen> with Submitter {
  late final _name = TextEditingController(text: widget.existing?['name'] as String? ?? '');
  late final _recipients = TextEditingController(text: ((widget.existing?['recipients'] as List?) ?? const []).join(', '));
  late String _schedule = widget.existing?['schedule'] as String? ?? 'none';
  late String _period = (widget.existing?['filters']?['period'] as String?) ?? (_periodLabels.containsKey(widget.period) ? widget.period! : 'last_30_days');

  @override
  void dispose() {
    _name.dispose();
    _recipients.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final body = {
      'name': _name.text.trim(),
      'analysis': widget.analysis,
      'filters': {...?(widget.existing?['filters'] as Map<String, dynamic>?), 'period': _period},
      if (widget.custom != null) 'custom': widget.custom,
      'schedule': _schedule,
      'recipients': [for (final r in _recipients.text.split(',')) if (r.trim().isNotEmpty) r.trim()],
    };
    final api = context.read<ApiClient>();
    final existing = widget.existing;
    if (existing == null) {
      await api.post('/analytics/saved', body);
    } else {
      await api.put('/analytics/saved/${existing['id']}', body);
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: widget.existing == null ? 'Save report' : 'Edit report',
        subtitle: 'Saved with a named period, so "last month" always means the month before the day it runs.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(label: 'Name', controller: _name, mandatory: true, minLength: 2, capitalization: TextCapitalization.sentences),
          ChoiceField<String>(label: 'Period', options: _periodLabels, value: _period, onChanged: (v) => setState(() => _period = v)),
          ChoiceField<String>(label: 'Email it', options: _schedules, value: _schedule, onChanged: (v) => setState(() => _schedule = v)),
          if (_schedule != 'none')
            AppTextField(
              label: 'To',
              controller: _recipients,
              mandatory: true,
              keyboardType: TextInputType.emailAddress,
              helper: 'Email addresses, separated by commas. The report comes as an Excel file.',
            ),
        ],
      );
}

/// Reports saved by anyone in the company, with their schedules.
class SavedReportsScreen extends StatelessWidget {
  const SavedReportsScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Saved reports')),
        body: Loader<List<dynamic>>(
          errorTitle: 'Could not load saved reports',
          load: () async => await context.read<ApiClient>().get('/analytics/saved/list') as List,
          builder: (context, rows) {
            final text = Theme.of(context).textTheme;
            final reports = rows.cast<Map<String, dynamic>>();
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                if (reports.isEmpty)
                  const MessageView(card: true, icon: Icons.bookmark_border, title: 'No saved reports', body: 'Build a report in Analytics and save it, or have it emailed on a schedule.'),
                for (final r in reports)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      onTap: r['analysis'] == 'custom'
                          ? () => Navigator.of(context).push(MaterialPageRoute<void>(
                                builder: (_) => CustomReportScreen(filters: {'period': (r['filters'] as Map)['period'] as String}, saved: r),
                              ))
                          : () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => SaveReportScreen(analysis: r['analysis'] as String, existing: r))),
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(r['name'] as String, style: text.titleMedium),
                          Text(
                            '${_periodLabels[(r['filters'] as Map)['period']] ?? ''} · ${_schedules[r['schedule']]}'
                            '${(r['recipients'] as List).isNotEmpty ? ' to ${(r['recipients'] as List).join(', ')}' : ''}',
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
