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
import '../delivery/delivery_screens.dart';
import '../tasks/tasks_screen.dart';

/// The operations dashboard: the owner sees every branch, a branch manager their own. The server
/// decides which; this screen shows what it is given.
class OperationsScreen extends StatelessWidget {
  const OperationsScreen({super.key});

  void _open(BuildContext context, Widget screen) =>
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Operations')),
        body: Loader<Map<String, dynamic>>(
          cacheKey: 'operations',
          errorTitle: 'Could not load operations',
          load: () async => await context.read<ApiClient>().get('/dashboard/operations') as Map<String, dynamic>,
          builder: (context, d) {
            final text = Theme.of(context).textTheme;
            final user = context.read<Session>().user!;
            final branches = (d['branches'] as List).cast<Map<String, dynamic>>();
            final late = (d['late_delivery_updates'] as List).cast<Map<String, dynamic>>();
            final staff = (d['staff'] as List).cast<Map<String, dynamic>>();
            final alerts = (d['alerts'] as List).cast<String>();
            Widget figure(String value, String label) => Expanded(child: MetricTile(value: value, label: label, onDark: true));
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                DarkPanel(
                  child: Column(
                    children: [
                      Row(children: [figure(money(d['receivable'] as String), 'Owed to us'), figure(money(d['overdue'] as String), 'Overdue')]),
                      const SizedBox(height: 14),
                      Row(children: [figure(money(d['collected_this_month'] as String), 'Collected this month'), figure('${d['escalated_tasks']}', 'Escalated tasks')]),
                      const SizedBox(height: 14),
                      Row(children: [figure('${d['lrs_this_month']}', 'LRs this month'), figure('${d['delivered_this_month']}', 'Delivered (signed)')]),
                      const SizedBox(height: 14),
                      Row(children: [figure('${d['delivered_unpaid']}', 'Delivered, unpaid'), figure('${d['overdue_lrs']}', 'Overdue LRs')]),
                    ],
                  ),
                ),
                if ((d['pending_approvals'] as int) > 0 && user.canDecideApproval) ...[
                  const SizedBox(height: 12),
                  AppCard(
                    color: Palette.primaryContainer,
                    onTap: () => _open(context, const ApprovalsScreen()),
                    child: ListTile(
                      leading: const Icon(Icons.how_to_vote_outlined, color: Palette.onPrimaryContainer),
                      title: Text('${d['pending_approvals']} approval${d['pending_approvals'] == 1 ? '' : 's'} waiting for you'),
                      trailing: const Icon(Icons.chevron_right),
                    ),
                  ),
                ],
                if (late.isNotEmpty) ...[
                  const SectionHeader('Unloaded but not signed for', icon: Icons.hourglass_empty),
                  Text(
                    'These LRs reached the destination godown, but no consignee signature is recorded.',
                    style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                  ),
                  const SizedBox(height: 8),
                  for (final l in late)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: AppCard(
                        onTap: () => _open(context, const GatePassesScreen()),
                        padding: const EdgeInsets.all(14),
                        child: Row(
                          children: [
                            Expanded(child: Text('${l['lr_number']} · ${l['consignee']}', style: text.bodyMedium)),
                            StatusChip.tone('${l['days']} days', (l['days'] as int) > 4 ? Tone.danger : Tone.warning),
                          ],
                        ),
                      ),
                    ),
                ],
                const SectionHeader('By branch', icon: Icons.apartment_outlined),
                for (final b in branches)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text(b['name'] as String, style: text.titleMedium)),
                              Text(money(b['receivable'] as String), style: text.labelLarge),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${b['lrs_this_month']} booked · ${b['awaiting_dispatch']} to dispatch · ${b['in_transit']} on the road · '
                            '${b['awaiting_delivery']} to deliver · ${b['delivered_this_month']} delivered\n'
                            'Overdue ${money(b['overdue'] as String)} · cash held ${money(b['cash_held'] as String)}',
                            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (staff.isNotEmpty) ...[
                  SectionHeader(
                    'Staff this month',
                    icon: Icons.groups_outlined,
                    trailing: TextButton(onPressed: () => _open(context, const TasksScreen()), child: const Text('Tasks')),
                  ),
                  for (final s in staff)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: AppCard(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(child: Text(s['name'] as String, style: text.titleMedium)),
                                if ((s['escalated_tasks'] as int) > 0) StatusChip.tone('${s['escalated_tasks']} escalated', Tone.danger),
                              ],
                            ),
                            Text(
                              'Collected ${money(s['collected_this_month'] as String)} · ${s['deliveries_this_month']} deliveries · '
                              '${s['open_tasks']} open tasks · holding ${money(s['cash_held'] as String)}',
                              style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                            ),
                          ],
                        ),
                      ),
                    ),
                ],
                SectionHeader('Needs attention · ${alerts.length}', icon: Icons.flag_outlined),
                if (alerts.isEmpty)
                  const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'All clear', body: 'Nothing needs a decision right now.'),
                for (final a in alerts)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: AppCard(
                      padding: const EdgeInsets.all(14),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.error_outline, color: Palette.warning, size: 20),
                          const SizedBox(width: 10),
                          Expanded(child: Text(a, style: text.bodyMedium)),
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

/// Requests waiting for the owner, and the history of decisions.
class ApprovalsScreen extends StatefulWidget {
  const ApprovalsScreen({super.key});

  @override
  State<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends State<ApprovalsScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();
  String _status = 'pending';

  /// Optimistic: the request leaves the list at once; if the server refuses, it comes back with the reason.
  Future<void> _decide(List<Map<String, dynamic>> shown, Map<String, dynamic> r, bool approve) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => shown.remove(r));
    try {
      await context.read<ApiClient>().post('/approvals/${r['id']}/decide', {'approve': approve});
      messenger.showSnackBar(SnackBar(content: Text('${r['lr_number']} ${approve ? 'approved' : 'rejected'}.')));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
    await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Approvals')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Segmented<String>(
              options: const {'pending': 'Waiting', 'approved': 'Approved', 'rejected': 'Rejected'},
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
              errorTitle: 'Could not load approvals',
              load: () async => await context.read<ApiClient>().get('/approvals', query: {'status': _status}) as List,
              builder: (context, rows) {
                final shown = rows.cast<Map<String, dynamic>>().toList();
                return ListView(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                  children: [
                    if (shown.isEmpty)
                      const MessageView(card: true, icon: Icons.inbox_outlined, title: 'Nothing here', body: 'No requests.'),
                    for (final r in shown)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: AppCard(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Release ${r['lr_number']} unpaid', style: text.titleMedium),
                              Text(
                                '${r['payer']} owes ${money(r['amount_owed'] as String)} · asked by ${r['requested_by']} '
                                '${dateTimeLabel(r['requested_at'] as String)}',
                                style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                              ),
                              const SizedBox(height: 6),
                              Text('"${r['reason']}"', style: text.bodyMedium),
                              if (r['decided_by'] != null)
                                Text(
                                  '${r['status'] == 'approved' ? 'Approved' : 'Rejected'} by ${r['decided_by']}'
                                  '${r['decision_note'] != null ? ': ${r['decision_note']}' : ''}',
                                  style: text.bodySmall,
                                ),
                              if (r['status'] == 'pending' && user.canDecideApproval) ...[
                                const SizedBox(height: 12),
                                Row(
                                  children: [
                                    Expanded(
                                      child: FilledButton(
                                        style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                                        onPressed: () => _decide(shown, r, true),
                                        child: const Text('Approve'),
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: OutlinedButton(
                                        style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
                                        onPressed: () => _decide(shown, r, false),
                                        child: const Text('Reject'),
                                      ),
                                    ),
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
          ),
        ],
      ),
    );
  }
}

/// Branches and the destination cities each one delivers.
class BranchesScreen extends StatefulWidget {
  const BranchesScreen({super.key});

  @override
  State<BranchesScreen> createState() => _BranchesScreenState();
}

class _BranchesScreenState extends State<BranchesScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();

  Future<void> _edit([Map<String, dynamic>? branch]) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => _BranchForm(branch: branch)));
    if (saved == true) await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Branches')),
        bottomNavigationBar: BottomBar(children: [BusyButton(icon: Icons.add, label: 'Add a branch', onPressed: _edit)]),
        body: Loader<List<dynamic>>(
          key: _loader,
          errorTitle: 'Could not load branches',
          load: () async => await context.read<ApiClient>().get('/branches') as List,
          builder: (context, rows) {
            final text = Theme.of(context).textTheme;
            return ListView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              children: [
                const PageIntro('Each branch sees only its own LRs, money and staff. An LR belongs to the branch that delivers its destination city.'),
                for (final b in rows.cast<Map<String, dynamic>>())
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppCard(
                      onTap: () => _edit(b),
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(child: Text(b['name'] as String, style: text.titleMedium)),
                              if (b['is_head_office'] as bool) StatusChip.tone('Head office', Tone.info),
                              if (!(b['is_active'] as bool)) StatusChip.tone('Closed', Tone.neutral),
                            ],
                          ),
                          Text(
                            (b['cities'] as List).isEmpty ? 'Delivers to no city yet' : 'Delivers to ${(b['cities'] as List).join(', ')}',
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

class _BranchForm extends StatefulWidget {
  const _BranchForm({this.branch});

  final Map<String, dynamic>? branch;

  @override
  State<_BranchForm> createState() => _BranchFormState();
}

class _BranchFormState extends State<_BranchForm> with Submitter {
  late final _name = TextEditingController(text: widget.branch?['name'] as String? ?? '');
  late final _address = TextEditingController(text: widget.branch?['address'] as String? ?? '');
  late final _phone = TextEditingController(text: widget.branch?['phone'] as String? ?? '');
  late final _cities = TextEditingController(text: ((widget.branch?['cities'] as List?) ?? const []).join(', '));
  late bool _active = widget.branch?['is_active'] as bool? ?? true;

  @override
  void dispose() {
    for (final c in [_name, _address, _phone, _cities]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    String? orNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
    final body = {
      'name': _name.text.trim(),
      'address': orNull(_address),
      'phone': orNull(_phone),
      'cities': [for (final c in _cities.text.split(',')) if (c.trim().isNotEmpty) c.trim()],
      'is_active': _active,
    };
    final api = context.read<ApiClient>();
    final branch = widget.branch;
    if (branch == null) {
      await api.post('/branches', body);
    } else {
      await api.put('/branches/${branch['id']}', body);
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: widget.branch == null ? 'Add branch' : 'Edit branch',
        subtitle: 'The address and phone print on this branch\'s gate passes and money receipts.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(label: 'Name', controller: _name, mandatory: true, capitalization: TextCapitalization.words, check: businessName),
          AppTextField(label: 'Address', controller: _address, lines: 2, capitalization: TextCapitalization.words, check: address),
          PhoneField(controller: _phone),
          AppTextField(
            label: 'Delivers to these cities',
            controller: _cities,
            capitalization: TextCapitalization.characters,
            helper: 'Separated by commas, e.g. RAIPUR, DHAMTARI. A city belongs to one branch.',
            check: cityList,
          ),
          if (widget.branch != null) SwitchField(label: 'Open', value: _active, onChanged: (v) => setState(() => _active = v)),
        ],
      );
}
