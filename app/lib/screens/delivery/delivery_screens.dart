import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/pod_queue.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import '../../widgets/pdf_screen.dart';
import '../../widgets/signature_pad.dart';
import '../money/receipt_screens.dart' show askReason;

StatusChip gatePassChip(String status) => switch (status) {
      'delivered' => StatusChip.tone('Delivered', Tone.success),
      'void' => StatusChip.tone('Cancelled', Tone.danger),
      _ => StatusChip.tone('Out for delivery', Tone.info),
    };

/// Gate passes: waiting to be delivered, delivered, cancelled. Also sends any proofs of delivery
/// saved on this phone while it was offline.
class GatePassesScreen extends StatefulWidget {
  const GatePassesScreen({super.key});

  @override
  State<GatePassesScreen> createState() => _GatePassesScreenState();
}

class _GatePassesScreenState extends State<GatePassesScreen> {
  final _loader = GlobalKey<LoaderState<List<dynamic>>>();
  String _status = 'issued';
  int _waiting = 0;

  @override
  void initState() {
    super.initState();
    _sendQueued();
  }

  Future<void> _sendQueued() async {
    final queue = context.read<PodQueue>();
    final messenger = ScaffoldMessenger.of(context);
    final (sent, refused) = await queue.flush();
    final left = await queue.count;
    if (!mounted) return;
    setState(() => _waiting = left);
    if (sent > 0) messenger.showSnackBar(SnackBar(content: Text('$sent saved deliver${sent == 1 ? 'y' : 'ies'} sent.')));
    for (final message in refused) {
      messenger.showSnackBar(SnackBar(content: Text('A saved delivery was refused: $message')));
    }
    if (sent > 0) await _loader.currentState?.reload();
  }

  Future<void> _open(Widget screen) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
    await _sendQueued();
    await _loader.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Gate passes')),
      bottomNavigationBar: user.canIssueGatePass
          ? BottomBar(children: [BusyButton(icon: Icons.add, label: 'New gate pass', onPressed: () => _open(const IssueGatePassScreen()))])
          : null,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Segmented<String>(
              options: const {'issued': 'To deliver', 'delivered': 'Delivered', 'void': 'Cancelled'},
              value: _status,
              onChanged: (v) {
                setState(() => _status = v);
                _loader.currentState?.reload();
              },
            ),
          ),
          if (_waiting > 0)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: AppCard(
                color: Palette.warningContainer,
                onTap: _sendQueued,
                padding: const EdgeInsets.all(14),
                child: Text(
                  '$_waiting deliver${_waiting == 1 ? 'y is' : 'ies are'} saved on this phone and not sent yet. Tap to try again.',
                  style: text.bodyMedium!.copyWith(color: Palette.warning),
                ),
              ),
            ),
          Expanded(
            child: Loader<List<dynamic>>(
              key: _loader,
              cacheKey: 'gate-passes-$_status',
              errorTitle: 'Could not load gate passes',
              load: () async => await context.read<ApiClient>().get('/gate-passes', query: {'status': _status}) as List,
              builder: (context, rows) {
                final passes = rows.cast<Map<String, dynamic>>();
                return ListView(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                  children: [
                    if (passes.isEmpty)
                      MessageView(
                        card: true,
                        icon: Icons.local_shipping_outlined,
                        title: _status == 'issued' ? 'Nothing out for delivery' : 'None here',
                        body: _status == 'issued' ? 'Issue a gate pass when a consignee comes for their goods.' : 'Try another filter.',
                      ),
                    for (final gp in passes)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: AppCard(
                          onTap: () => _open(GatePassScreen(gatePassId: gp['id'] as String)),
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(child: Text('No. ${gp['gate_pass_number']}', style: text.titleMedium)),
                                  gatePassChip(gp['status'] as String),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(gp['consignee_name'] as String, style: text.labelLarge),
                              Text(
                                [
                                  for (final l in (gp['lines'] as List)) l['lr_number'] as String,
                                ].join(', '),
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

/// Release one consignee's goods: search their LRs, tick the ones going out, name the vehicle.
class IssueGatePassScreen extends StatefulWidget {
  const IssueGatePassScreen({super.key, this.lr});

  /// Start from this LR (from LR detail): its consignee's other LRs are offered too.
  final Map<String, dynamic>? lr;

  @override
  State<IssueGatePassScreen> createState() => _IssueGatePassScreenState();
}

class _IssueGatePassScreenState extends State<IssueGatePassScreen> with Submitter {
  final _key = newIdempotencyKey();
  late final _search = TextEditingController(text: widget.lr?['consignee_name'] as String? ?? '');
  final _auto = TextEditingController();
  final _driver = TextEditingController();
  List<Map<String, dynamic>> _found = const [];
  final Set<String> _chosen = {};
  bool _searching = false;

  @override
  void initState() {
    super.initState();
    if (widget.lr != null) {
      _chosen.add(widget.lr!['id'] as String);
      _find();
    }
  }

  @override
  void dispose() {
    for (final c in [_search, _auto, _driver]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _find() async {
    final q = _search.text.trim();
    if (q.isEmpty) return;
    setState(() => _searching = true);
    try {
      final rows = await context.read<ApiClient>().get('/lrs', query: {'q': q, 'limit': '50'}) as List;
      if (!mounted) return;
      setState(() => _found = [for (final r in rows.cast<Map<String, dynamic>>()) if (r['status'] == 'confirmed') r]);
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => _searching = false);
    }
  }

  Future<void> _issue() async {
    if (_chosen.isEmpty) throw const ApiException(0, 'Tick at least one LR.');
    final auto = _auto.text.trim();
    final driver = _driver.text.trim();
    final gp = await context.read<ApiClient>().post(
      '/gate-passes',
      {'lr_ids': _chosen.toList(), if (auto.isNotEmpty) 'auto_no': auto, if (driver.isNotEmpty) 'driver_name': driver},
      idempotencyKey: _key,
    ) as Map<String, dynamic>;
    if (!mounted) return;
    await Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(builder: (_) => GatePassScreen(gatePassId: gp['id'] as String)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'New gate pass',
      subtitle: 'One consignee per gate pass. To-pay LRs must be paid, on credit, or approved by the owner.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Issue gate pass',
      onSubmit: () => submit(_issue),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: AppTextField(
                label: 'Consignee or LR number',
                controller: _search,
                mandatory: true,
                capitalization: TextCapitalization.characters,
              ),
            ),
            const SizedBox(width: 10),
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: IconButton.filled(
                tooltip: 'Search',
                onPressed: _searching ? null : _find,
                icon: _searching
                    ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.search),
              ),
            ),
          ],
        ),
        for (final lr in _found)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: AppCard(
              child: CheckboxListTile(
                value: _chosen.contains(lr['id']),
                onChanged: (on) => setState(() => on == true ? _chosen.add(lr['id'] as String) : _chosen.remove(lr['id'])),
                title: Text('${lr['lr_number']} · ${lr['packages']} pkgs', style: text.titleMedium),
                subtitle: Text('${lr['consignee_name']} · ${lr['freight_by']} · ${money(lr['total'] as String)}', style: text.bodySmall),
              ),
            ),
          ),
        const SizedBox(height: 8),
        AppTextField(label: 'Auto / vehicle number', controller: _auto, capitalization: TextCapitalization.characters, hint: 'e.g. CG04AB1234'),
        AppTextField(label: 'Driver name', controller: _driver, capitalization: TextCapitalization.words),
      ],
    );
  }
}

/// One gate pass: its LRs, print, record delivery, and (with the permission) cancel or undo.
class GatePassScreen extends StatefulWidget {
  const GatePassScreen({super.key, required this.gatePassId});

  final String gatePassId;

  @override
  State<GatePassScreen> createState() => _GatePassScreenState();
}

class _GatePassScreenState extends State<GatePassScreen> {
  final _loader = GlobalKey<LoaderState<Map<String, dynamic>>>();

  Future<void> _deliver(Map<String, dynamic> gp) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => DeliveryProofScreen(gatePass: gp)));
    await _loader.currentState?.reload();
  }

  Future<void> _void(Map<String, dynamic> gp) async {
    final reason = await askReason(
      context,
      title: gp['status'] == 'delivered' ? 'Undo this delivery?' : 'Cancel this gate pass?',
      hint: 'Why, for the record',
    );
    if (reason == null || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().post('/gate-passes/${widget.gatePassId}/void', {'reason': reason});
      await _loader.currentState?.reload();
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    final text = Theme.of(context).textTheme;
    return Loader<Map<String, dynamic>>(
      key: _loader,
      errorTitle: 'Could not load the gate pass',
      load: () async => await context.read<ApiClient>().get('/gate-passes/${widget.gatePassId}') as Map<String, dynamic>,
      builder: (context, gp) {
        final issued = gp['status'] == 'issued';
        return Scaffold(
          appBar: AppBar(
            title: Text('Gate pass ${gp['gate_pass_number']}'),
            actions: [
              IconButton(
                tooltip: 'Print',
                icon: const Icon(Icons.print_outlined),
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => PdfScreen(
                      title: 'Gate pass ${gp['gate_pass_number']}',
                      path: '/gate-passes/${widget.gatePassId}/pdf',
                      fileName: 'gate-pass-${gp['gate_pass_number']}.pdf',
                    ),
                  ),
                ),
              ),
            ],
          ),
          bottomNavigationBar: issued && user.canConfirmDelivery
              ? BottomBar(children: [BusyButton(icon: Icons.draw_outlined, label: 'Record delivery', onPressed: () => _deliver(gp))])
              : null,
          body: ListView(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
            children: [
              DarkPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(gp['consignee_name'] as String, style: onInk(text.titleLarge!))),
                        gatePassChip(gp['status'] as String),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Issued by ${gp['issued_by']} · ${dateTimeLabel(gp['issued_at'] as String)}'
                      '${gp['auto_no'] != null ? ' · auto ${gp['auto_no']}' : ''}'
                      '${gp['driver_name'] != null ? ' · ${gp['driver_name']}' : ''}',
                      style: onInk(text.bodySmall!, muted: true),
                    ),
                  ],
                ),
              ),
              const SectionHeader('LRs', icon: Icons.receipt_long_outlined),
              AppCard(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(
                  children: [
                    for (final l in (gp['lines'] as List).cast<Map<String, dynamic>>())
                      ListTile(
                        title: Text(l['lr_number'] as String, style: text.titleMedium),
                        subtitle: Text('${l['packages']} packages'),
                        trailing: StatusChip.tone(l['payment'] as String, l['basis'] == 'approved' ? Tone.warning : Tone.success),
                      ),
                  ],
                ),
              ),
              if (gp['status'] == 'delivered' || gp['receiver_name'] != null) ...[
                const SectionHeader('Proof of delivery', icon: Icons.verified_outlined),
                AppCard(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Received by ${gp['receiver_name']}', style: text.titleMedium),
                      Text(
                        [
                          if (gp['delivered_at'] != null) dateTimeLabel(gp['delivered_at'] as String),
                          if (gp['receiver_phone'] != null) gp['receiver_phone'] as String,
                          if (gp['pod_recorded_by'] != null) 'recorded by ${gp['pod_recorded_by']}',
                          if (gp['latitude'] != null) 'located',
                        ].join(' · '),
                        style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                      ),
                      if (gp['has_photo'] as bool) ...[
                        const SizedBox(height: 12),
                        _PodPhoto(gatePassId: widget.gatePassId),
                      ],
                    ],
                  ),
                ),
              ],
              if (gp['void_reason'] != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: ErrorBanner('Cancelled: ${gp['void_reason']}'),
                ),
              if (gp['status'] != 'void' && user.canCorrectDelivery)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: TextButton(
                    style: TextButton.styleFrom(foregroundColor: Palette.error),
                    onPressed: () => _void(gp),
                    child: Text(gp['status'] == 'delivered' ? 'Undo this delivery' : 'Cancel this gate pass'),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

/// The photo of the signed paper, fetched with the user's sign-in.
class _PodPhoto extends StatelessWidget {
  const _PodPhoto({required this.gatePassId});

  final String gatePassId;

  @override
  Widget build(BuildContext context) => FutureBuilder(
        future: context.read<ApiClient>().getBytes('/gate-passes/$gatePassId/photo'),
        builder: (context, snapshot) => AspectRatio(
          aspectRatio: 4 / 3,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: snapshot.hasData
                ? Image.memory(snapshot.data!, fit: BoxFit.cover, gaplessPlayback: true)
                // A flat placeholder of the card colour until the photo arrives.
                : Container(color: Palette.disabled),
          ),
        ),
      );
}

/// The consignee signs for the goods. Takes the time at signing, the place when the phone allows,
/// and a photo of the signed paper gate pass. Without a connection it is kept on the phone and sent later.
class DeliveryProofScreen extends StatefulWidget {
  const DeliveryProofScreen({super.key, required this.gatePass});

  final Map<String, dynamic> gatePass;

  @override
  State<DeliveryProofScreen> createState() => _DeliveryProofScreenState();
}

class _DeliveryProofScreenState extends State<DeliveryProofScreen> with Submitter {
  final _key = newIdempotencyKey();
  late final _receiver = TextEditingController(text: widget.gatePass['consignee_name'] as String);
  final _phone = TextEditingController();
  List<List<Offset>> _signature = const [];
  DateTime? _signedAt;
  List<int>? _photo;
  Position? _position;
  String? _locationNote;

  @override
  void initState() {
    super.initState();
    _locate();
  }

  @override
  void dispose() {
    _receiver.dispose();
    _phone.dispose();
    super.dispose();
  }

  /// Ask once for the place. Delivery is recorded without it if the phone says no.
  Future<void> _locate() async {
    try {
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
        if (mounted) setState(() => _locationNote = 'Location not allowed on this phone; delivery is recorded without it.');
        return;
      }
      final position = await Geolocator.getCurrentPosition().timeout(const Duration(seconds: 10));
      if (mounted) setState(() => _position = position);
    } catch (_) {
      if (mounted) setState(() => _locationNote = 'Could not get the location; delivery is recorded without it.');
    }
  }

  Future<void> _takePhoto() async {
    final shot = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 60, maxWidth: 1600);
    if (shot == null) return;
    final bytes = await shot.readAsBytes();
    if (mounted) setState(() => _photo = bytes);
  }

  Future<void> _save() async {
    if (_signature.fold<int>(0, (n, s) => n + s.length) < 8) {
      throw const ApiException(0, 'Ask the consignee to sign in the box.');
    }
    final signedAt = _signedAt ?? DateTime.now();
    final phone = _phone.text.trim();
    final proof = jsonEncode({
      'delivered_at': signedAt.toUtc().toIso8601String(),
      'receiver_name': _receiver.text.trim(),
      if (phone.isNotEmpty) 'receiver_phone': phone,
      'signature': [
        for (final stroke in _signature) [for (final p in stroke) [p.dx.roundToDouble(), p.dy.roundToDouble()]],
      ],
      if (_position != null) 'latitude': _position!.latitude,
      if (_position != null) 'longitude': _position!.longitude,
      if (_position != null) 'accuracy_m': _position!.accuracy,
    });
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ApiClient>().postForm(
        '/gate-passes/${widget.gatePass['id']}/delivery',
        {'proof': proof},
        file: _photo == null ? null : (Uint8List.fromList(_photo!), 'gate-pass.jpg'),
        fileField: 'photo',
        idempotencyKey: _key,
      );
      messenger.showSnackBar(const SnackBar(content: Text('Delivery recorded.')));
    } on ApiException catch (e) {
      if (e.status != 0) rethrow;
      // No connection: keep it, with the signing time, and send it when the phone is back online.
      await context.read<PodQueue>().add(gatePassId: widget.gatePass['id'] as String, proofJson: proof, key: _key, photo: _photo);
      messenger.showSnackBar(const SnackBar(content: Text('No connection. Saved on this phone; it will be sent from Gate passes.')));
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Proof of delivery',
      subtitle: 'Gate pass ${widget.gatePass['gate_pass_number']}. Hand the phone to the consignee to sign.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Confirm delivery',
      onSubmit: () => submit(_save),
      children: [
        AppTextField(label: 'Received by', controller: _receiver, mandatory: true, minLength: 2, capitalization: TextCapitalization.words),
        AppTextField(label: 'Their phone', controller: _phone, keyboardType: TextInputType.phone),
        Text('Signature', style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant)),
        const SizedBox(height: 8),
        SignaturePad(
          onChanged: (strokes) {
            _signature = strokes;
            // The delivery time is when they signed, not when it reaches the office.
            _signedAt = strokes.isEmpty ? null : (_signedAt ?? DateTime.now());
          },
        ),
        const SizedBox(height: 8),
        AppCard(
          onTap: _takePhoto,
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Icon(_photo == null ? Icons.photo_camera_outlined : Icons.check_circle, color: _photo == null ? Palette.onSurface : Palette.success),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  _photo == null ? 'Photo of the signed paper gate pass' : 'Photo taken. Tap to take again.',
                  style: text.titleMedium,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Text(
          _position != null
              ? 'Location recorded (within ${_position!.accuracy.round()} m).'
              : _locationNote ?? 'Getting the location…',
          style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
        ),
      ],
    );
  }
}
