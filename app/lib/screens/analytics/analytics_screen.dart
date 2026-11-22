import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/charts.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/pdf_screen.dart';
import 'custom_report_screen.dart';

/// What the analyses are filtered by. Every analysis takes the same filters, so switching tabs
/// keeps the question the same.
class AnalyticsFilters {
  const AnalyticsFilters({
    this.period = 'last_30_days',
    this.dateFrom,
    this.dateTo,
    this.customer,
    this.origin,
    this.destination,
    this.freightBy,
    this.stage,
  });

  final String period;
  final DateTime? dateFrom;
  final DateTime? dateTo;
  final String? customer;
  final String? origin;
  final String? destination;
  final String? freightBy;
  final String? stage;

  AnalyticsFilters copyWith({
    String? period,
    DateTime? dateFrom,
    DateTime? dateTo,
    String? Function()? customer,
    String? Function()? origin,
    String? Function()? destination,
    String? Function()? freightBy,
    String? Function()? stage,
  }) =>
      AnalyticsFilters(
        period: period ?? this.period,
        dateFrom: period != null ? null : dateFrom ?? this.dateFrom,
        dateTo: period != null ? null : dateTo ?? this.dateTo,
        customer: customer != null ? customer() : this.customer,
        origin: origin != null ? origin() : this.origin,
        destination: destination != null ? destination() : this.destination,
        freightBy: freightBy != null ? freightBy() : this.freightBy,
        stage: stage != null ? stage() : this.stage,
      );

  Map<String, String> toQuery() => {
        if (dateFrom != null && dateTo != null) ...{
          'date_from': dateFrom!.toIso8601String().substring(0, 10),
          'date_to': dateTo!.toIso8601String().substring(0, 10),
        } else
          'period': period,
        if (customer != null) 'customer': customer!,
        if (origin != null) 'origin': origin!,
        if (destination != null) 'destination': destination!,
        if (freightBy != null) 'freight_by': freightBy!,
        if (stage != null) 'stage': stage!,
      };

  /// A short line of the filters in force, beyond the period.
  String get narrowing => [
        if (customer != null) customer!,
        if (origin != null) 'from $origin',
        if (destination != null) 'to $destination',
        if (freightBy != null) freightBy!,
        if (stage != null) stage!.replaceAll('_', ' '),
      ].join(' · ');
}

const _periods = {
  'last_7_days': '7 days',
  'last_30_days': '30 days',
  'this_month': 'This month',
  'last_month': 'Last month',
  'this_quarter': 'This quarter',
  'this_year': 'This year',
};

const _tabs = {
  'overview': 'Overview',
  'insights': 'Insights',
  'customers': 'Customers',
  'lanes': 'Routes',
  'rates': 'Rates',
  'execution': 'Delivery',
  'fleet': 'Trucks',
  'finance': 'Money',
  'trip_profit': 'Trip profit',
  'vendors': 'Truck owners',
  'rfqs': 'Quotes',
  'contracts': 'Contracts',
  'branches': 'Branches',
};

/// Views that show money, needing the money-trail permission as well.
const _moneyTabs = {'finance', 'trip_profit', 'vendors'};

String _num(dynamic v, {int places = 0}) {
  if (v == null) return '-';
  final n = v is String ? double.parse(v) : (v as num).toDouble();
  return places == 0 ? n.round().toString() : n.toStringAsFixed(places);
}

String _rs(dynamic v) => v == null ? '-' : rupees(v is String ? double.parse(v) : (v as num).toDouble());

/// Business analytics: the same filters across every view, figures from the app's own records,
/// each view saying how its figures were worked out, and every view exportable to Excel or PDF.
class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  AnalyticsFilters _filters = const AnalyticsFilters();
  String _tab = 'overview';

  String get _grain {
    final days = _filters.dateFrom != null && _filters.dateTo != null
        ? _filters.dateTo!.difference(_filters.dateFrom!).inDays
        : switch (_filters.period) {
            'last_7_days' || 'last_30_days' || 'this_month' || 'last_month' => 31,
            'this_quarter' => 92,
            _ => 366,
          };
    return days <= 31 ? 'day' : days <= 120 ? 'week' : 'month';
  }

  void _setFilters(AnalyticsFilters f) => setState(() => _filters = f);

  /// Open a view with one more filter, as a drill-down from a row.
  void _drill(String tab, AnalyticsFilters f) => setState(() {
        _filters = f;
        _tab = tab;
      });

  Future<void> _pickRange() async {
    final now = DateTime.now();
    final range = await showDateRangePicker(context: context, firstDate: DateTime(now.year - 3), lastDate: now);
    if (range != null) _setFilters(AnalyticsFilters(dateFrom: range.start, dateTo: range.end, customer: _filters.customer, origin: _filters.origin, destination: _filters.destination, freightBy: _filters.freightBy, stage: _filters.stage));
  }

  Future<void> _moreFilters() async {
    final picked = await showModalBottomSheet<AnalyticsFilters>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _FilterSheet(filters: _filters),
    );
    if (picked != null) _setFilters(picked);
  }

  Future<void> _export(String format) async {
    final query = {..._filters.toQuery(), if (_tab == 'trend' || _tab == 'overview') 'grain': _grain, 'format': format};
    final path = '/analytics/$_tab/export?${Uri(queryParameters: query).query}';
    if (format == 'pdf') {
      await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => PdfScreen(title: _tabs[_tab]!, path: path, fileName: '$_tab.pdf')));
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await context.read<ApiClient>().getBytes(path);
      await shareSpreadsheet(bytes, '$_tab.xlsx');
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    final text = Theme.of(context).textTheme;
    final tabs = {for (final e in _tabs.entries) if (!_moneyTabs.contains(e.key) || user.canSeeMoneyTrail) e.key: e.value};
    return Scaffold(
      appBar: AppBar(
        title: const Text('Analytics'),
        actions: [
          IconButton(
            tooltip: 'Build a report',
            icon: const Icon(Icons.tune),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => CustomReportScreen(filters: _filters.toQuery()))),
          ),
          PopupMenuButton<String>(
            tooltip: 'Export',
            icon: const Icon(Icons.ios_share),
            onSelected: _export,
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'xlsx', child: Text('Excel (all columns)')),
              PopupMenuItem(value: 'pdf', child: Text('PDF')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 20),
              children: [
                for (final p in _periods.entries)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(p.value),
                      selected: _filters.dateFrom == null && _filters.period == p.key,
                      labelStyle: text.labelMedium!.copyWith(color: _filters.dateFrom == null && _filters.period == p.key ? Palette.onInk : Palette.onSurface),
                      onSelected: (_) => _setFilters(_filters.copyWith(period: p.key)),
                    ),
                  ),
                ActionChip(
                  label: Text(_filters.dateFrom == null ? 'Dates…' : '${dayLabel(_filters.dateFrom!.toIso8601String().substring(0, 10))} – ${dayLabel(_filters.dateTo!.toIso8601String().substring(0, 10))}'),
                  onPressed: _pickRange,
                ),
                const SizedBox(width: 8),
                ActionChip(
                  avatar: const Icon(Icons.filter_list, size: 18),
                  label: Text(_filters.narrowing.isEmpty ? 'Filters' : _filters.narrowing),
                  onPressed: _moreFilters,
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 20),
              children: [
                for (final t in tabs.entries)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: TextButton(
                      style: TextButton.styleFrom(
                        backgroundColor: _tab == t.key ? Palette.ink : null,
                        foregroundColor: _tab == t.key ? Palette.onInk : Palette.onSurfaceVariant,
                        shape: const StadiumBorder(),
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                      ),
                      onPressed: () => setState(() => _tab = t.key),
                      child: Text(t.value),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: KeyedSubtree(
              key: ValueKey('$_tab ${_filters.toQuery()}'),
              child: _view(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _view() {
    final query = _filters.toQuery();
    Future<dynamic> get(String name, [Map<String, String> extra = const {}]) =>
        context.read<ApiClient>().get('/analytics/$name', query: {...query, ...extra});
    final key = '$_tab ${jsonEncode(query)}';
    return switch (_tab) {
      'overview' => Loader<(Map<String, dynamic>, Map<String, dynamic>)>(
          cacheKey: key,
          errorTitle: 'Could not load the overview',
          load: () async => (await get('overview') as Map<String, dynamic>, await get('trend', {'grain': _grain}) as Map<String, dynamic>),
          builder: (context, d) => _OverviewView(overview: d.$1, trend: d.$2),
        ),
      'insights' => Loader<List<dynamic>>(
          cacheKey: key,
          errorTitle: 'Could not work out insights',
          load: () async => await get('insights') as List,
          builder: (context, rows) => _InsightsView(insights: rows.cast<Map<String, dynamic>>(), open: (tab) => setState(() => _tab = tab)),
        ),
      _ => Loader<Map<String, dynamic>>(
          cacheKey: key,
          errorTitle: 'Could not load ${_tabs[_tab]}',
          load: () async => await get(_tab) as Map<String, dynamic>,
          builder: (context, d) => switch (_tab) {
            'customers' => _CustomersView(data: d, onCustomer: (c) => _drill('overview', _filters.copyWith(customer: () => c))),
            'lanes' => _LanesView(data: d, onLane: (o, dest) => _drill('rates', _filters.copyWith(origin: () => o, destination: () => dest))),
            'rates' => _RatesView(data: d),
            'execution' => _ExecutionView(data: d),
            'fleet' => _TableView(data: d, rowsKey: 'rows', columns: const {
                'vehicle_number': 'Truck', 'trips': 'Trips', 'lrs': 'LRs', 'weight_carried': 'Weight (kg)',
                'avg_payload_used_pct': 'Payload used %', 'days_on_road': 'Days on road',
              }),
            'finance' => _FinanceView(data: d),
            'trip_profit' => _TripProfitView(data: d),
            'vendors' => _TableView(data: d, rowsKey: 'rows', columns: const {
                'vendor': 'Truck owner', 'trips': 'Trips', 'revenue_carried': 'Freight carried', 'hire': 'Hire',
                'hire_share_pct': 'Hire % of freight', 'margin_pct': 'Margin %', 'on_time_pct': 'On time %',
                'deductions': 'Deducted', 'owed_now': 'Owed now', 'quotes_given': 'Quotes', 'win_rate_pct': 'Won %',
              }),
            'rfqs' => _RfqSummaryView(data: d),
            'contracts' => _ContractsView(data: d),
            _ => _TableView(data: d, rowsKey: 'rows', columns: const {
                'branch': 'Branch', 'lrs_booked': 'Booked', 'revenue_booked': 'Revenue', 'lrs_delivered': 'Delivered',
                'median_days_unload_to_signature': 'Days to signature', 'collection_rate_pct': 'Collected %', 'cash_handed_over_short': 'Cash short',
              }),
          },
        ),
    };
  }
}

/// Share an Excel file to whatever the phone offers: email, WhatsApp, Drive, Files.
Future<void> shareSpreadsheet(Uint8List bytes, String name) => SharePlus.instance.share(
      ShareParams(
        files: [XFile.fromData(bytes, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', name: name)],
        fileNameOverrides: [name],
      ),
    );

/// How the figures were worked out, under every view.
class _Basis extends StatelessWidget {
  const _Basis(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.info_outline, size: 16, color: Palette.onSurfaceMuted),
            const SizedBox(width: 6),
            Expanded(child: Text(text, style: Theme.of(context).textTheme.bodySmall!.copyWith(color: Palette.onSurfaceMuted))),
          ],
        ),
      );
}

class _OverviewView extends StatelessWidget {
  const _OverviewView({required this.overview, required this.trend});

  final Map<String, dynamic> overview;
  final Map<String, dynamic> trend;

  String _value(Map<String, dynamic> k) => switch (k['unit']) {
        'rupees' => _rs(k['value']),
        'rupees_per_kg' => k['value'] == null ? '-' : '₹${_num(k['value'], places: 2)}',
        'percent' => k['value'] == null ? '-' : '${_num(k['value'], places: 1)}%',
        'days' => k['value'] == null ? '-' : '${_num(k['value'], places: 1)} d',
        'kg' => k['value'] == null ? '-' : kgLabel(k['value'] as num),
        _ => _num(k['value']),
      };

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final kpis = (overview['kpis'] as List).cast<Map<String, dynamic>>();
    final points = [
      for (final p in (trend['points'] as List).cast<Map<String, dynamic>>())
        ChartPoint(p['label'] as String, double.parse(p['revenue'] as String), secondary: double.parse(p['collected'] as String)),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          childAspectRatio: 1.55,
          children: [
            for (final k in kpis)
              AppCard(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(k['label'] as String, maxLines: 2, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
                    const Spacer(),
                    FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(_value(k), style: text.titleLarge)),
                    if (k['change_pct'] != null)
                      Text(
                        '${(k['change_pct'] as num) >= 0 ? '▲' : '▼'} ${_num((k['change_pct'] as num).abs(), places: 1)}% vs before',
                        style: text.bodySmall!.copyWith(color: (k['change_pct'] as num) >= 0 ? Palette.success : Palette.error),
                      ),
                  ],
                ),
              ),
          ],
        ),
        const SectionHeader('Revenue and collections', icon: Icons.bar_chart),
        AppCard(
          padding: const EdgeInsets.all(16),
          child: BarLineChart(points: points, format: (v) => rupees(v), barLegend: 'Revenue booked', lineLegend: 'Collected'),
        ),
        _Basis(overview['basis'] as String),
      ],
    );
  }
}

class _InsightsView extends StatelessWidget {
  const _InsightsView({required this.insights, required this.open});

  final List<Map<String, dynamic>> insights;
  final ValueChanged<String> open;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    if (insights.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: const [MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Nothing unusual', body: 'No rule found anything that needs your attention in this period.')],
      );
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        for (final i in insights)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              onTap: () => open(i['analysis'] as String),
              padding: const EdgeInsets.all(16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    i['severity'] == 'high' ? Icons.error_outline : i['severity'] == 'medium' ? Icons.warning_amber_rounded : Icons.lightbulb_outline,
                    color: i['severity'] == 'high' ? Palette.error : i['severity'] == 'medium' ? Palette.warning : Palette.onSurfaceVariant,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(i['title'] as String, style: text.titleMedium),
                        const SizedBox(height: 4),
                        Text(i['detail'] as String, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
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
  }
}

class _CustomersView extends StatelessWidget {
  const _CustomersView({required this.data, required this.onCustomer});

  final Map<String, dynamic> data;
  final ValueChanged<String> onCustomer;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final rows = (data['rows'] as List).cast<Map<String, dynamic>>();
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        if (data['top3_share_pct'] != null)
          PageIntro('The top three customers bring ${_num(data['top3_share_pct'], places: 0)}% of revenue. Tap a customer for their own figures.'),
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              onTap: () => onCustomer(r['customer'] as String),
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(child: Text(r['customer'] as String, style: text.titleMedium)),
                      Text(_rs(r['revenue']), style: text.labelLarge),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    [
                      '${r['lrs']} LRs',
                      '${_num(r['share_pct'], places: 1)}% of revenue',
                      if (r['growth_pct'] != null) '${(r['growth_pct'] as num) >= 0 ? '+' : ''}${_num(r['growth_pct'], places: 0)}% vs before',
                      if (r['avg_days_between_bookings'] != null) 'books every ${_num(r['avg_days_between_bookings'], places: 0)} days',
                      if (r['median_days_to_pay'] != null) 'pays in ${_num(r['median_days_to_pay'], places: 0)} days',
                      if (r['owes_now'] != null && double.parse(r['owes_now'] as String) > 0) 'owes ${_rs(r['owes_now'])}',
                    ].join(' · '),
                    style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                  ),
                ],
              ),
            ),
          ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

class _LanesView extends StatelessWidget {
  const _LanesView({required this.data, required this.onLane});

  final Map<String, dynamic> data;
  final void Function(String origin, String destination) onLane;

  @override
  Widget build(BuildContext context) {
    final rows = (data['rows'] as List).cast<Map<String, dynamic>>();
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        const PageIntro('Tap a route for its rates.'),
        DataGrid(
          columns: const ['Route', 'LRs', 'Revenue', 'Share %', 'Weight (kg)', '₹/kg', 'Days on road', 'Customers'],
          rows: [
            for (final r in rows)
              [
                '${r['origin']} → ${r['destination']}',
                '${r['lrs']}',
                _rs(r['revenue']),
                _num(r['share_pct'], places: 1),
                _num(r['weight']),
                _num(r['revenue_per_kg'], places: 2),
                _num(r['median_transit_days'], places: 1),
                '${r['customers']}',
              ],
          ],
          onTap: (i) => onLane(rows[i]['origin'] as String, rows[i]['destination'] as String),
        ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

class _RatesView extends StatelessWidget {
  const _RatesView({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final lanes = (data['lanes'] as List).cast<Map<String, dynamic>>();
    final outliers = (data['outliers'] as List).cast<Map<String, dynamic>>();
    final history = (data['history'] as List).cast<Map<String, dynamic>>();
    final kg = [for (final h in history) if (h['avg_rate_per_kg'] != null) ChartPoint(h['month'] as String, (h['avg_rate_per_kg'] as num).toDouble())];
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        DataGrid(
          columns: const ['Route', 'Per', 'LRs', 'Median', 'Low', 'High', 'Middle half'],
          rows: [
            for (final r in lanes)
              [
                '${r['origin']} → ${r['destination']}',
                r['unit'] == 'per_kg' ? 'kg' : 'article',
                '${r['samples']}',
                '₹${_num(r['median'], places: 2)}',
                '₹${_num(r['minimum'], places: 2)}',
                '₹${_num(r['maximum'], places: 2)}',
                '₹${_num(r['p25'], places: 2)} – ₹${_num(r['p75'], places: 2)}',
              ],
          ],
        ),
        if (kg.length > 1) ...[
          const SectionHeader('Average rate per kg, by month', icon: Icons.show_chart),
          AppCard(padding: const EdgeInsets.all(16), child: BarLineChart(points: kg, format: (v) => '₹${v.toStringAsFixed(2)}/kg')),
        ],
        SectionHeader('Unusual rates · ${outliers.length}', icon: Icons.priority_high),
        if (outliers.isEmpty) const PageIntro('None: every LR is within the usual range of its route.'),
        for (final o in outliers)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: AppCard(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Expanded(child: Text('${o['lr_number']} · ${o['customer']} · ${dayLabel(o['lr_date'] as String)}')),
                  StatusChip.tone('₹${_num(o['rate'], places: 2)} vs ₹${_num(o['lane_median'], places: 2)}', o['direction'] == 'low' ? Tone.danger : Tone.warning),
                ],
              ),
            ),
          ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

class _ExecutionView extends StatelessWidget {
  const _ExecutionView({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final stages = (data['stages'] as Map).cast<String, dynamic>();
    final durations = (data['durations'] as List).cast<Map<String, dynamic>>();
    final pending = (data['pending'] as List).cast<Map<String, dynamic>>();
    final delayed = (data['delayed'] as List).cast<Map<String, dynamic>>();
    const labels = {'awaiting_dispatch': 'To dispatch', 'in_transit': 'On the road', 'awaiting_delivery': 'To deliver', 'delivered': 'Delivered'};
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        DarkPanel(
          child: Row(
            children: [
              for (final s in labels.entries) Expanded(child: MetricTile(value: '${stages[s.key]}', label: s.value, onDark: true)),
            ],
          ),
        ),
        if (data['on_time_pct'] != null) ...[
          const SizedBox(height: 10),
          Text('${_num(data['on_time_pct'], places: 0)}% of judged trips took their route\'s usual time.', style: text.bodyMedium),
        ],
        const SectionHeader('How long each stage takes', icon: Icons.timelapse),
        DataGrid(
          columns: const ['Stage', 'LRs', 'Median days', '9 in 10 within'],
          rows: [for (final d in durations) [d['stage'] as String, '${d['samples']}', _num(d['median_days'], places: 1), _num(d['p90_days'], places: 1)]],
        ),
        SectionHeader('Waiting longest · ${pending.length}', icon: Icons.hourglass_bottom),
        for (final p in pending.take(20))
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text('${p['lr_number']} · ${p['customer']} · ${labels[p['stage']]} for ${p['days']} days', style: text.bodyMedium),
          ),
        SectionHeader('Slower than usual · ${delayed.length}', icon: Icons.slow_motion_video),
        for (final d in delayed.take(20))
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text('${d['lr_number']} · ${d['origin']} → ${d['destination']} · ${_num(d['transit_days'], places: 1)} days (usual ${_num(d['lane_median_days'], places: 1)})', style: text.bodyMedium),
          ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

class _FinanceView extends StatelessWidget {
  const _FinanceView({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final months = [...(data['months'] as List).cast<Map<String, dynamic>>(), data['totals'] as Map<String, dynamic>];
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        DarkPanel(
          child: Row(
            children: [
              Expanded(child: MetricTile(value: _rs(data['receivable_now']), label: 'Owed now', onDark: true)),
              Expanded(child: MetricTile(value: _rs(data['overdue_now']), label: 'Overdue now', onDark: true)),
              Expanded(child: MetricTile(value: data['median_days_to_payment'] == null ? '-' : '${_num(data['median_days_to_payment'])} d', label: 'Median days to be paid', onDark: true)),
            ],
          ),
        ),
        const SizedBox(height: 12),
        DataGrid(
          columns: const ['Month', 'Booked', 'Cash', 'UPI', 'Cheque', 'Transfer', 'Collected', 'In bank', 'Shortages'],
          rows: [
            for (final m in months)
              [m['month'] as String, _rs(m['revenue_booked']), _rs(m['collected_cash']), _rs(m['collected_upi']), _rs(m['collected_cheque']), _rs(m['collected_bank']), _rs(m['collected_total']), _rs(m['confirmed_by_bank']), _rs(m['shortages'])],
          ],
        ),
        Padding(padding: const EdgeInsets.only(top: 12), child: ErrorBanner(data['expenses_note'] as String)),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

/// Columns that hold names, never numbers to format.
const _textColumns = {'vehicle_number', 'branch', 'vendor'};

/// A view that is one table: [columns] maps field to heading, in order.
class _TableView extends StatelessWidget {
  const _TableView({required this.data, required this.rowsKey, required this.columns});

  final Map<String, dynamic> data;
  final String rowsKey;
  final Map<String, String> columns;

  @override
  Widget build(BuildContext context) {
    final rows = (data[rowsKey] as List).cast<Map<String, dynamic>>();
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        if (rows.isEmpty) const MessageView(card: true, icon: Icons.inbox_outlined, title: 'Nothing in this period', body: 'Try a longer period or fewer filters.'),
        if (rows.isNotEmpty)
          DataGrid(
            columns: columns.values.toList(),
            rows: [
              for (final r in rows)
                [for (final key in columns.keys) r[key] is String && double.tryParse(r[key] as String) != null && !_textColumns.contains(key) ? _num(r[key], places: 2) : '${r[key] ?? '-'}'],
            ],
          ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

class _FilterSheet extends StatefulWidget {
  const _FilterSheet({required this.filters});

  final AnalyticsFilters filters;

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late String? _customer = widget.filters.customer;
  late String? _origin = widget.filters.origin;
  late String? _destination = widget.filters.destination;
  late String? _freightBy = widget.filters.freightBy;
  late String? _stage = widget.filters.stage;

  Widget _pick(String label, List<String> options, String? value, ValueChanged<String?> onChanged) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: DropdownButtonFormField<String?>(
          value: value,
          isExpanded: true,
          decoration: InputDecoration(labelText: label),
          items: [
            const DropdownMenuItem(value: null, child: Text('Any')),
            for (final o in options) DropdownMenuItem(value: o, child: Text(o, overflow: TextOverflow.ellipsis)),
          ],
          onChanged: onChanged,
        ),
      );

  @override
  Widget build(BuildContext context) => FutureBuilder(
        future: context.read<ApiClient>().get('/analytics/options'),
        builder: (context, snapshot) {
          final o = (snapshot.data as Map<String, dynamic>?) ?? const {'customers': [], 'origins': [], 'destinations': []};
          List<String> list(String key) => (o[key] as List).cast<String>();
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            shrinkWrap: true,
            children: [
              Text('Filters', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 16),
              _pick('Customer (who pays)', list('customers'), _customer, (v) => setState(() => _customer = v)),
              _pick('From', list('origins'), _origin, (v) => setState(() => _origin = v)),
              _pick('To', list('destinations'), _destination, (v) => setState(() => _destination = v)),
              _pick('Freight by', const ['Paid', 'ToPay', 'TBB'], _freightBy, (v) => setState(() => _freightBy = v)),
              _pick('Stage', const ['awaiting_dispatch', 'in_transit', 'awaiting_delivery', 'delivered'], _stage, (v) => setState(() => _stage = v)),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(widget.filters.copyWith(
                  customer: () => _customer,
                  origin: () => _origin,
                  destination: () => _destination,
                  freightBy: () => _freightBy,
                  stage: () => _stage,
                )),
                child: const Text('Apply'),
              ),
            ],
          );
        },
      );
}


class _TripProfitView extends StatelessWidget {
  const _TripProfitView({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final trips = (data['trips'] as List).cast<Map<String, dynamic>>();
    final routes = (data['by_destination'] as List).cast<Map<String, dynamic>>();
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        DarkPanel(
          child: Column(
            children: [
              Row(
                children: [
                  Expanded(child: MetricTile(value: _rs(data['revenue']), label: 'Freight carried', onDark: true)),
                  Expanded(child: MetricTile(value: _rs(data['hire']), label: 'Truck hire', onDark: true)),
                ],
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(child: MetricTile(value: _rs(data['margin']), label: 'Left for us', onDark: true)),
                  Expanded(
                    child: MetricTile(
                      value: data['margin_pct'] == null ? '-' : '${_num(data['margin_pct'], places: 1)}%',
                      label: 'Margin · hire is ${_num(data['hire_share_pct'], places: 0)}% of freight',
                      onDark: true,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        if ((data['trips_without_hire'] as int) > 0)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: ErrorBanner('${data['trips_without_hire']} trip(s) have no hire recorded and are left out. Record it on each trip.'),
          ),
        const SectionHeader('By destination, lowest margin first', icon: Icons.route_outlined),
        DataGrid(
          columns: const ['To', 'Trips', 'Freight', 'Hire', 'Left', 'Margin %'],
          rows: [for (final r in routes) [r['destination'] as String, '${r['trips']}', _rs(r['revenue']), _rs(r['hire']), _rs(r['margin']), _num(r['margin_pct'], places: 1)]],
        ),
        const SectionHeader('Trips, lowest margin first', icon: Icons.local_shipping_outlined),
        DataGrid(
          columns: const ['Trip', 'Truck', 'Owner', 'To', 'Freight', 'Hire', 'Expenses', 'Left', 'Margin %'],
          rows: [
            for (final t in trips)
              ['${t['trip_no']}', t['vehicle_number'] as String, '${t['vendor_name']}', t['destination'] as String, _rs(t['revenue']), _rs(t['hire']), _rs(t['expenses']), _rs(t['margin']), _num(t['margin_pct'], places: 1)],
          ],
        ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}

class _RfqSummaryView extends StatelessWidget {
  const _RfqSummaryView({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        children: [
          DarkPanel(
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(child: MetricTile(value: '${data['requests']}', label: 'Requests', onDark: true)),
                    Expanded(child: MetricTile(value: '${data['awarded']}', label: 'Awarded', onDark: true)),
                    Expanded(child: MetricTile(value: data['response_rate_pct'] == null ? '-' : '${_num(data['response_rate_pct'])}%', label: 'Owners who quoted', onDark: true)),
                  ],
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(child: MetricTile(value: _rs(data['saved_vs_highest']), label: 'Saved against the highest quote', onDark: true)),
                    Expanded(child: MetricTile(value: _rs(data['saved_by_revisions']), label: 'Saved by owners lowering their price', onDark: true)),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          DataGrid(
            columns: const ['Measure', 'Value'],
            rows: [
              ['Quotes per request', _num(data['avg_quotes_per_request'], places: 1)],
              ['Hire awarded in all', _rs(data['awarded_total'])],
              ['Hours from request to award (median)', _num(data['median_hours_to_award'], places: 1)],
              ['Still open', '${data['open']}'],
              ['Cancelled', '${data['cancelled']}'],
            ],
          ),
          _Basis(data['basis'] as String),
        ],
      );
}

class _ContractsView extends StatelessWidget {
  const _ContractsView({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final rows = (data['rows'] as List).cast<Map<String, dynamic>>();
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        if (rows.isEmpty) const MessageView(card: true, icon: Icons.description_outlined, title: 'No contracts in this period', body: 'Add them under Account, Customer contracts.'),
        for (final c in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(child: Text(c['party'] as String, style: text.titleMedium)),
                      StatusChip.tone(
                        c['status'] == 'expiring' ? 'Ends in ${c['days_left']} days' : (c['status'] as String),
                        c['status'] == 'expired' ? Tone.danger : c['status'] == 'expiring' ? Tone.warning : Tone.success,
                      ),
                    ],
                  ),
                  Text(
                    '${c['lrs']} LRs under contract · ${_rs(c['revenue'])} · ${c['on_rate']} at the agreed rate'
                    '${(c['lrs_after_expiry'] as int) > 0 ? ' · ${c['lrs_after_expiry']} booked after it ended' : ''}',
                    style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                  ),
                  for (final o in (c['off_rate'] as List).cast<Map<String, dynamic>>().take(5))
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text('${o['lr_number']} to ${o['destination']}: charged ${o['charged']}, agreed ${o['agreed']}', style: text.bodySmall!.copyWith(color: Palette.error)),
                    ),
                ],
              ),
            ),
          ),
        _Basis(data['basis'] as String),
      ],
    );
  }
}
