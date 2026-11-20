import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/signature_pad.dart';

StatusChip _statusChip(String status) => switch (status) {
      'requested' =>
        const StatusChip('Waiting for approval', background: Palette.warningContainer, foreground: Palette.warning),
      'awaiting_driver' =>
        const StatusChip('Waiting for driver', background: Palette.warningContainer, foreground: Palette.warning),
      'void' => const StatusChip('Void', background: Palette.errorContainer, foreground: Palette.error),
      _ => const StatusChip('Issued', background: Palette.successContainer, foreground: Palette.success),
    };

/// One challan: the primary one from the origin, or cargo added on the road, with what can be
/// done to it by the person looking. [onChanged] is called after any action so the caller reloads.
class ChallanCard extends StatelessWidget {
  const ChallanCard({super.key, required this.challan, required this.onChanged, this.showTruck = false});

  final Map<String, dynamic> challan;
  final VoidCallback onChanged;

  /// Show which truck it is for; used in lists that span trips.
  final bool showTruck;

  Future<void> _post(BuildContext context, String action, Map<String, dynamic> body, String done) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/challans/${challan['id']}/$action', body);
      messenger.showSnackBar(SnackBar(content: Text(done)));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
    onChanged();
  }

  Future<void> _void(BuildContext context) async {
    final reason = await showDialog<String>(context: context, builder: (_) => const _ReasonDialog());
    if (reason != null && context.mounted) {
      await _post(context, 'void', {'reason': reason}, '${challan['challan_number']} voided.');
    }
  }

  Future<void> _sign(BuildContext context) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => DriverSignScreen(challan: challan)));
    onChanged();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final muted = StatusColors.of(context).muted;
    final status = challan['status'] as String;
    final lines = (challan['lines'] as List).cast<Map<String, dynamic>>();
    final warnings = (challan['warnings'] as List).cast<String>();
    final added = (challan['seq'] as int) > 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(child: Text(challan['challan_number'] as String, style: text.titleMedium)),
                  _statusChip(status),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                [
                  if (showTruck) 'Truck ${challan['vehicle_number']}',
                  added ? 'Added at ${challan['loaded_at']}' : 'Loaded at ${challan['loaded_at']}',
                ].join(' · '),
                style: text.labelMedium,
              ),
              Text(
                [
                  'Asked by ${challan['requested_by']}',
                  if (challan['approved_by'] != null) 'approved by ${challan['approved_by']}',
                  if (challan['driver_name'] != null) 'signed by driver ${challan['driver_name']}',
                  dateTimeLabel((challan['issued_at'] ?? challan['created_at']) as String),
                ].join(' · '),
                style: text.bodySmall!.copyWith(color: muted),
              ),
              const SizedBox(height: 8),
              for (final line in lines)
                Text(
                  '${line['lr_number']} · ${line['consignee_name']} · ${line['to_city']} · '
                  '${line['loaded'] == null ? '${line['requested']} packages' : '${line['loaded']} of ${line['requested']} loaded'}',
                  style: text.bodyMedium,
                ),
              if (challan['shortage_note'] != null)
                Text('Short: ${challan['shortage_note']}', style: text.bodyMedium!.copyWith(color: Palette.warning)),
              if (challan['void_reason'] != null)
                Text('Voided: ${challan['void_reason']}', style: text.bodyMedium!.copyWith(color: Palette.error)),
              if (challan['sealed'] == false)
                Text(
                  'Warning: this challan no longer matches its seal. Its lines were changed outside the app.',
                  style: text.bodyMedium!.copyWith(color: Palette.error),
                ),
              for (final warning in warnings)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(warning, style: text.bodyMedium!.copyWith(color: Palette.warning)),
                ),
              if (challan['can_approve'] as bool || challan['can_sign'] as bool || challan['can_void'] as bool)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Wrap(
                    spacing: 8,
                    children: [
                      if (challan['can_approve'] as bool)
                        FilledButton(
                          style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                          onPressed: () => _post(context, 'approve', {}, '${challan['challan_number']} approved.'),
                          child: const Text('Approve'),
                        ),
                      if (challan['can_sign'] as bool)
                        FilledButton(
                          style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                          onPressed: () => _sign(context),
                          child: const Text('Driver sign-off'),
                        ),
                      if (challan['can_void'] as bool)
                        TextButton(
                          style: TextButton.styleFrom(foregroundColor: Palette.error),
                          onPressed: () => _void(context),
                          child: Text(status == 'requested' ? 'Refuse' : 'Void'),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ReasonDialog extends StatefulWidget {
  const _ReasonDialog();

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
        title: const Text('Why?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('The challan keeps its number and stays on record with this reason.'),
            const SizedBox(height: 16),
            TextField(
              controller: _reason,
              autofocus: true,
              maxLength: 200,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(hintText: 'For example: goods not ready'),
            ),
          ],
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

/// Ask to load more cargo onto a truck that is already on the road. Pops with `true` once sent.
class AddCargoScreen extends StatefulWidget {
  const AddCargoScreen({super.key, required this.trip});

  final Map<String, dynamic> trip;

  @override
  State<AddCargoScreen> createState() => _AddCargoScreenState();
}

class _AddCargoScreenState extends State<AddCargoScreen> with Submitter {
  static const _elsewhere = '';

  late final List<String> _stops = [for (final s in (widget.trip['stops'] as List)) s['city'] as String];
  final _place = TextEditingController();

  /// An existing stop, or [_elsewhere] for a place that is not on the route yet.
  late String _loadedAt = _elsewhere;
  late String _before = _stops.first;
  List<Map<String, dynamic>>? _lrs;
  String? _loadError;
  final Map<String, TextEditingController> _load = {};

  @override
  void initState() {
    super.initState();
    _loadLrs();
  }

  @override
  void dispose() {
    _place.dispose();
    for (final c in _load.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadLrs() async {
    setState(() => _loadError = null);
    try {
      final lrs = await context.read<ApiClient>().get('/pending/lrs', query: {'destination': _stops.join(',')}) as List;
      if (!mounted) return;
      setState(() {
        _lrs = lrs.cast<Map<String, dynamic>>();
        for (final lr in _lrs!) {
          _load[lr['lr_id'] as String] = TextEditingController(text: '0');
        }
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  Future<void> _send() async {
    final lines = [
      for (final lr in _lrs!)
        if ((int.tryParse(_load[lr['lr_id']]!.text.trim()) ?? 0) > 0)
          {'lr_id': lr['lr_id'], 'packages': int.parse(_load[lr['lr_id']]!.text.trim())},
    ];
    if (lines.isEmpty) throw const ApiException(0, 'Enter the packages to load for at least one LR.');
    final elsewhere = _loadedAt == _elsewhere;
    final challan = await context.read<ApiClient>().post('/trips/${widget.trip['id']}/additions', {
      'loaded_at': elsewhere ? _place.text.trim() : _loadedAt,
      if (elsewhere) 'insert_before': _before,
      'lines': lines,
    }) as Map<String, dynamic>;
    if (!mounted) return;
    final warnings = (challan['warnings'] as List).cast<String>();
    await showDialog<void>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text('${challan['challan_number']} sent for approval'),
        content: Text(
          [
            'Nothing is on the truck yet. It needs approval from the person who dispatched the trip, '
                'then the driver signs for what is loaded.',
            ...warnings,
          ].join('\n\n'),
        ),
        actions: [TextButton(onPressed: () => Navigator.of(dialog).pop(), child: const Text('OK'))],
      ),
    );
    if (mounted) Navigator.of(context).pop(true);
  }

  String? _checkLoad(String value, int pending) {
    final n = int.tryParse(value);
    if (n == null || n < 0) return 'Whole number';
    return n > pending ? 'Only $pending pending' : null;
  }

  @override
  Widget build(BuildContext context) {
    final title = 'Add cargo to ${widget.trip['vehicle_number']}';
    final lrs = _lrs;
    if (lrs == null) {
      return Scaffold(
        appBar: AppBar(title: Text(title)),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                title: 'Could not load the pending goods',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _loadLrs,
              ),
      );
    }
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: title,
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Send for approval',
      onSubmit: () => submit(_send),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            'The truck is on its way to ${_stops.join(' → ')}. The original challan stays as it is; '
            'this cargo goes on a new one.',
            style: text.bodyMedium,
          ),
        ),
        ChoiceField<String>(
          label: 'Loading at',
          options: {_elsewhere: 'Another place', for (final stop in _stops) stop: stop},
          value: _loadedAt,
          onChanged: (v) => setState(() => _loadedAt = v),
        ),
        if (_loadedAt == _elsewhere) ...[
          AppTextField(
            label: 'Place',
            controller: _place,
            mandatory: true,
            capitalization: TextCapitalization.characters,
          ),
          ChoiceField<String>(
            label: 'The truck reaches it before',
            options: {for (final stop in _stops) stop: stop},
            value: _before,
            onChanged: (v) => setState(() => _before = v),
          ),
        ],
        Text('Packages to add', style: text.titleMedium),
        const SizedBox(height: 12),
        if (lrs.isEmpty) Text('No pending LR is for a stop on this trip.', style: text.bodyMedium),
        for (final lr in lrs)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: AppCard(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('${lr['lr_number']} · ${lr['consignee_name']}', style: text.titleMedium),
                          const SizedBox(height: 4),
                          Text(
                            '${(lr['to_city'] as String).toUpperCase()} · ${lr['pending']} pending · '
                            '${waitingLabel(lr['days_waiting'] as int)}',
                            style: text.bodyMedium,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    SizedBox(
                      width: 96,
                      child: TextFormField(
                        controller: _load[lr['lr_id']],
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        style: text.bodyLarge,
                        validator: (v) => _checkLoad(v?.trim() ?? '', lr['pending'] as int),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// The driver counts what was put on the truck and signs for it. Pops with `true` once signed.
class DriverSignScreen extends StatefulWidget {
  const DriverSignScreen({super.key, required this.challan});

  final Map<String, dynamic> challan;

  @override
  State<DriverSignScreen> createState() => _DriverSignScreenState();
}

class _DriverSignScreenState extends State<DriverSignScreen> with Submitter {
  late final List<Map<String, dynamic>> _lines = (widget.challan['lines'] as List).cast<Map<String, dynamic>>();
  late final Map<String, TextEditingController> _counts = {
    for (final line in _lines) line['lr_id'] as String: TextEditingController(text: '${line['requested']}'),
  };
  final _driver = TextEditingController();
  List<List<Offset>> _signature = const [];

  @override
  void dispose() {
    _driver.dispose();
    for (final c in _counts.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _sign() async {
    if (_signature.fold<int>(0, (n, stroke) => n + stroke.length) < 8) {
      throw const ApiException(0, 'The driver has not signed yet.');
    }
    await context.read<ApiClient>().post('/challans/${widget.challan['id']}/sign', {
      'driver_name': _driver.text.trim(),
      'signature': [
        for (final stroke in _signature) [for (final p in stroke) [p.dx.roundToDouble(), p.dy.roundToDouble()]],
      ],
      'counts': [
        for (final line in _lines) {'lr_id': line['lr_id'], 'packages': int.parse(_counts[line['lr_id']]!.text.trim())},
      ],
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('${widget.challan['challan_number']} issued. The goods are on the truck.')),
    );
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Driver sign-off · ${widget.challan['challan_number']}',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Confirm and issue the challan',
      onSubmit: () => submit(_sign),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            'Hand the phone to the driver. Enter what was actually counted onto the truck: '
            'the driver answers only for that.',
            style: text.bodyMedium,
          ),
        ),
        for (final line in _lines)
          AppTextField(
            label: '${line['lr_number']} · ${line['consignee_name']} · ${line['to_city']}',
            controller: _counts[line['lr_id']]!,
            mandatory: true,
            keyboardType: TextInputType.number,
            unit: 'of ${line['requested']}',
            check: (v) {
              final n = int.tryParse(v);
              if (n == null || n < 0) return 'Whole number';
              return n > (line['requested'] as int) ? 'Only ${line['requested']} were approved' : null;
            },
          ),
        AppTextField(
          label: "Driver's name",
          controller: _driver,
          mandatory: true,
          minLength: 2,
          capitalization: TextCapitalization.words,
        ),
        Text("Driver's signature", style: text.labelMedium),
        const SizedBox(height: 8),
        SignaturePad(onChanged: (strokes) => _signature = strokes),
        const SizedBox(height: 16),
      ],
    );
  }
}
