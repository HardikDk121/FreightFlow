import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';

const _outcomes = {
  'called': 'Called',
  'visited': 'Visited',
  'not_available': 'Not available',
  'promised': 'Promised to pay',
  'refused': 'Refused',
  'paid': 'Paid',
};

StatusChip taskChip(Map<String, dynamic> t) {
  if (t['escalated'] as bool) return StatusChip.tone('Escalated', Tone.danger);
  if (t['status'] == 'promised') return StatusChip.tone('Promised ${dayLabel(t['next_action_on'] as String)}', Tone.warning);
  if (t['status'] == 'done') return StatusChip.tone('Done', Tone.success);
  return StatusChip.tone('Due ${dayLabel(t['next_action_on'] as String)}', Tone.info);
}

/// Collection tasks the app has created. Collectors see theirs; managers see everyone's.
class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();
  late String _scope = context.read<Session>().user!.canManageTasks ? 'all' : 'mine';

  Future<void> _open(Map<String, dynamic> task) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => TaskScreen(task: task)));
    await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Collection tasks')),
      body: Column(
        children: [
          if (user.canManageTasks)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Segmented<String>(
                options: const {'mine': 'Mine', 'all': 'Everyone'},
                value: _scope,
                onChanged: (v) {
                  setState(() => _scope = v);
                  _loader.currentState?.reload();
                },
              ),
            ),
          Expanded(
            child: Loader<List<dynamic>>(
              key: _loader,
              cacheKey: 'tasks-$_scope',
              errorTitle: 'Could not load tasks',
              load: () async => await context.read<ApiClient>().get('/tasks', query: {'scope': _scope}) as List,
              builder: (context, rows) {
                final tasks = rows.cast<Map<String, dynamic>>();
                final total = tasks.fold<double>(0, (n, t) => n + double.parse(t['amount_due'] as String));
                return ListView(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                  children: [
                    PageIntro(
                      tasks.isEmpty
                          ? 'The app makes a task when a customer\'s money falls due, and closes it when they have paid.'
                          : '${tasks.length} customer${tasks.length == 1 ? '' : 's'} to collect ${rupees(total)} from. Escalated ones first.',
                    ),
                    if (tasks.isEmpty)
                      const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Nothing to chase', body: 'No customer has money due.'),
                    for (final t in tasks)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: AppCard(
                          onTap: () => _open(t),
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(child: Text(t['payer_name'] as String, style: text.titleMedium)),
                                  taskChip(t),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '${money(t['amount_due'] as String)} · ${t['days_overdue']} days overdue'
                                '${_scope == 'all' ? ' · ${t['assigned_name'] ?? 'nobody assigned'}' : ''}',
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
}

/// One customer to chase: what is owed, what was tried, and recording the next try.
class TaskScreen extends StatefulWidget {
  const TaskScreen({super.key, required this.task});

  final Map<String, dynamic> task;

  @override
  State<TaskScreen> createState() => _TaskScreenState();
}

class _TaskScreenState extends State<TaskScreen> with Submitter {
  late Map<String, dynamic> _task = widget.task;
  String _outcome = 'called';
  DateTime? _promised;
  final _note = TextEditingController();

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _record() async {
    if (_outcome == 'promised' && _promised == null) throw const ApiException(0, 'Choose the date they promised.');
    final note = _note.text.trim();
    final updated = await context.read<ApiClient>().post('/tasks/${_task['id']}/attempts', {
      'outcome': _outcome,
      if (_outcome == 'promised') 'promised_on': _promised!.toIso8601String().substring(0, 10),
      if (note.isNotEmpty) 'note': note,
    }) as Map<String, dynamic>;
    if (!mounted) return;
    setState(() {
      _task = updated;
      _note.clear();
      _promised = null;
    });
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Recorded.')));
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final attempts = (_task['attempts'] as List).cast<Map<String, dynamic>>();
    final open = _task['status'] == 'open' || _task['status'] == 'promised';
    return FormPage(
      title: _task['payer_name'] as String,
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Record this attempt',
      onSubmit: open ? () => submit(_record) : null,
      children: [
        DarkPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(child: MetricTile(value: money(_task['amount_due'] as String), label: 'Due', onDark: true)),
                  Expanded(child: MetricTile(value: '${_task['days_overdue']}', label: 'Days overdue', onDark: true)),
                ],
              ),
              const SizedBox(height: 10),
              Text('Assigned to ${_task['assigned_name'] ?? 'nobody'}', style: onInk(text.bodySmall!, muted: true)),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (open) ...[
          ChoiceField<String>(label: 'What happened', options: _outcomes, value: _outcome, onChanged: (v) => setState(() => _outcome = v)),
          if (_outcome == 'promised')
            PickerField(
              label: 'Promised to pay by',
              value: _promised == null ? null : dayLabel(_promised!.toIso8601String().substring(0, 10)),
              placeholder: 'Choose a date',
              icon: Icons.calendar_today_outlined,
              onTap: () async {
                final today = DateUtils.dateOnly(DateTime.now());
                final picked = await showDatePicker(context: context, firstDate: today, lastDate: today.add(const Duration(days: 90)), initialDate: today.add(const Duration(days: 1)));
                if (picked != null) setState(() => _promised = picked);
              },
            ),
          AppTextField(label: 'Note', controller: _note, mandatory: _outcome == 'refused', lines: 2, capitalization: TextCapitalization.sentences),
          Text(
            'To record money received, use a money receipt under Collections. The task closes by itself once paid.',
            style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
          ),
        ],
        const SectionHeader('History', icon: Icons.history),
        if (attempts.isEmpty) Text('Nobody has tried yet.', style: text.bodyMedium),
        for (final a in attempts)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              '${dateTimeLabel(a['attempted_at'] as String)} · ${a['user']} · ${_outcomes[a['outcome']]}'
              '${a['promised_on'] != null ? ' by ${dayLabel(a['promised_on'] as String)}' : ''}'
              '${a['note'] != null ? ': ${a['note']}' : ''}',
              style: text.bodyMedium,
            ),
          ),
      ],
    );
  }
}
