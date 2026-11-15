import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'lr_page.dart';

const _freightByOptions = {'ToPay': 'To pay', 'Paid': 'Paid', 'TBB': 'To be billed'};

/// A new LR. Starts from the company defaults, picks up the consignor's last LR,
/// and is only saved when the person confirms the printed preview. Pops with `true` once saved.
class LrFormScreen extends StatefulWidget {
  const LrFormScreen({super.key});

  @override
  State<LrFormScreen> createState() => _LrFormScreenState();
}

class _LrFormScreenState extends State<LrFormScreen> with Submitter {
  final _from = TextEditingController();
  final _to = TextEditingController();
  final _consignor = TextEditingController();
  final _consignorGstin = TextEditingController();
  final _consignee = TextEditingController();
  final _consigneeGstin = TextEditingController();
  final _goods = TextEditingController();
  final _packages = TextEditingController();
  final _weight = TextEditingController();
  final _chargedWeight = TextEditingController();
  final _rate = TextEditingController();
  final _freight = TextEditingController();
  final _hamali = TextEditingController();
  final _otherCharges = TextEditingController();
  final _stCharges = TextEditingController();
  final _value = TextEditingController();
  final _ewayBill = TextEditingController();
  DateTime _date = DateTime.now();
  String _freightBy = 'ToPay';

  /// What one package is, for the load planner. Null when not set.
  String? _itemTypeId;
  List<Map<String, dynamic>> _itemTypes = const [];
  bool _scanning = false;

  /// Provisional: the server assigns the real number when the LR is saved.
  String? _nextNumber;
  String? _loadError;

  /// Fields the app filled in that the person has not touched yet.
  final Set<String> _filledByApp = {};
  bool _freightByChosen = false;
  String _lastSuggestedFor = '';

  late final List<TextEditingController> _charges = [_freight, _hamali, _otherCharges, _stCharges];

  @override
  void initState() {
    super.initState();
    _loadDefaults();
  }

  @override
  void dispose() {
    for (final c in [
      _from, _to, _consignor, _consignorGstin, _consignee, _consigneeGstin, _goods, _packages, _weight,
      _chargedWeight, _rate, _freight, _hamali, _otherCharges, _stCharges, _value, _ewayBill,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadDefaults() async {
    setState(() => _loadError = null);
    try {
      final api = context.read<ApiClient>();
      final defaults = await api.get('/lrs/defaults') as Map<String, dynamic>;
      final itemTypes = await api.get('/item-types', query: {'limit': '200'}) as List;
      if (!mounted) return;
      setState(() {
        _itemTypes = itemTypes.cast<Map<String, dynamic>>();
        _nextNumber = defaults['next_lr_number'] as String;
        _fill('from', _from, defaults['from_city'] as String?);
        final st = double.parse(defaults['st_charges'] as String);
        if (st > 0) _fill('st_charges', _stCharges, st.toStringAsFixed(2));
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  /// Put an app-supplied value in an empty field and mark it for checking. Never overwrites typing.
  void _fill(String key, TextEditingController controller, String? value) {
    if (value == null || value.isEmpty || controller.text.trim().isNotEmpty) return;
    controller.text = value;
    _filledByApp.add(key);
  }

  void _touched(String key) {
    if (_filledByApp.remove(key)) setState(() {});
  }

  /// When the person leaves the consignor field, reuse what this consignor's last LR had.
  Future<void> _suggestFromLastLr() async {
    final name = _consignor.text.trim();
    final gstin = _consignorGstin.text.trim();
    final key = '$name|$gstin';
    if ((name.isEmpty && gstin.isEmpty) || key == _lastSuggestedFor) return;
    _lastSuggestedFor = key;
    try {
      final s = await context.read<ApiClient>().get('/lrs/suggestions', query: {
        if (name.isNotEmpty) 'consignor_name': name,
        if (gstin.isNotEmpty) 'consignor_gstin': gstin,
      }) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        final freightBy = s['freight_by'] as String?;
        if (freightBy != null && !_freightByChosen) {
          _freightBy = freightBy;
          _filledByApp.add('freight_by');
        }
        _fill('goods', _goods, s['goods_description'] as String?);
        _fill('packages', _packages, (s['packages'] as int?)?.toString());
        _fill('consignor_gstin', _consignorGstin, s['consignor_gstin'] as String?);
        final itemType = s['item_type_id'] as String?;
        if (_itemTypeId == null && _itemTypes.any((t) => t['id'] == itemType)) {
          _itemTypeId = itemType;
          _filledByApp.add('item_type');
        }
      });
    } on ApiException {
      // Suggestions are a convenience; the form works without them.
    }
  }

  /// Photograph or pick an invoice, read it on the server, and fill the empty fields from it.
  Future<void> _scanInvoice() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Take a photo'),
              onTap: () => Navigator.of(sheet).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose from gallery'),
              onTap: () => Navigator.of(sheet).pop(ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;
    final photo = await ImagePicker().pickImage(source: source, imageQuality: 90, maxWidth: 2400);
    if (photo == null || !mounted) return;
    setState(() {
      _scanning = true;
      error = null;
    });
    final api = context.read<ApiClient>();
    final messenger = ScaffoldMessenger.of(context);
    try {
      final scan = await api.postImage('/invoices/scan', await photo.readAsBytes(), photo.name) as Map<String, dynamic>;
      if (!mounted) return;
      final before = _filledByApp.length;
      setState(() {
        _fill('consignor', _consignor, scan['consignor_name'] as String?);
        _fill('consignor_gstin', _consignorGstin, scan['consignor_gstin'] as String?);
        _fill('consignee', _consignee, scan['consignee_name'] as String?);
        _fill('consignee_gstin', _consigneeGstin, scan['consignee_gstin'] as String?);
        _fill('to', _to, scan['to_city'] as String?);
        _fill('goods', _goods, scan['goods_description'] as String?);
        _fill('value', _value, scan['value'] as String?);
        _fill('eway_bill', _ewayBill, scan['eway_bill_no'] as String?);
      });
      final filled = _filledByApp.length - before;
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            filled == 0
                ? 'Nothing could be read from that photo. Try a sharper one.'
                : 'Filled $filled fields from the invoice. Check the amber ones.',
          ),
        ),
      );
      // The consignor is now known, so bring in what its last LR had.
      await _suggestFromLastLr();
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  Future<void> _pickItemType() async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(title: const Text('Not set'), onTap: () => Navigator.of(sheet).pop('')),
            for (final t in _itemTypes)
              ListTile(
                title: Text(t['name'] as String),
                onTap: () => Navigator.of(sheet).pop(t['id'] as String),
              ),
          ],
        ),
      ),
    );
    if (picked == null) return;
    setState(() {
      _itemTypeId = picked.isEmpty ? null : picked;
      _filledByApp.remove('item_type');
    });
  }

  static String? _checkNumber(String value) => double.tryParse(value) == null ? 'Enter a number' : null;

  static String? _checkWholeNumber(String value) => int.tryParse(value) == null ? 'Enter a whole number' : null;

  static String? _checkEwayBill(String value) =>
      RegExp(r'^[0-9]{12}$').hasMatch(value) ? null : 'An e-way bill number has 12 digits';

  static String _isoDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  double get _total => _charges.fold(0, (sum, c) => sum + (double.tryParse(c.text.trim()) ?? 0));

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked != null) setState(() => _date = picked);
  }

  /// Blank optional fields are left out, so the server prints them empty (or as 0.00 for charges).
  Map<String, dynamic> _fields() {
    final body = <String, dynamic>{
      'lr_date': _isoDate(_date),
      'from_city': _from.text.trim(),
      'to_city': _to.text.trim(),
      'freight_by': _freightBy,
      'consignor_name': _consignor.text.trim(),
      'consignee_name': _consignee.text.trim(),
      'goods_description': _goods.text.trim(),
      'packages': int.parse(_packages.text.trim()),
    };
    final optional = {
      'consignor_gstin': _consignorGstin,
      'consignee_gstin': _consigneeGstin,
      'weight': _weight,
      'charged_weight': _chargedWeight,
      'rate': _rate,
      'freight': _freight,
      'hamali': _hamali,
      'other_charges': _otherCharges,
      'st_charges': _stCharges,
      'value': _value,
      'eway_bill_no': _ewayBill,
    };
    for (final entry in optional.entries) {
      final text = entry.value.text.trim();
      if (text.isNotEmpty) body[entry.key] = text;
    }
    if (_itemTypeId != null) body['item_type_id'] = _itemTypeId;
    return body;
  }

  Future<void> _preview() async {
    final fields = _fields();
    final pdf = await context
        .read<ApiClient>()
        .postForBytes('/lrs/print-preview', {...fields, 'lr_number': _nextNumber!});
    if (!mounted) return;
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => LrConfirmScreen(preview: pdf, fields: fields)),
    );
    if (saved == true && mounted) Navigator.of(context).pop(true);
  }

  AppTextField _field(
    String key,
    String label,
    TextEditingController controller, {
    bool mandatory = false,
    String? Function(String)? check,
    TextInputType? keyboardType,
    TextCapitalization capitalization = TextCapitalization.characters,
  }) =>
      AppTextField(
        label: label,
        controller: controller,
        mandatory: mandatory,
        check: check,
        keyboardType: keyboardType,
        capitalization: capitalization,
        highlighted: _filledByApp.contains(key),
        onChanged: (_) => _touched(key),
      );

  AppTextField _number(String key, String label, TextEditingController controller) => _field(
        key,
        label,
        controller,
        check: _checkNumber,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
      );

  Widget _section(String title) => Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 12),
        child: Text(title, style: Theme.of(context).textTheme.titleMedium),
      );

  @override
  Widget build(BuildContext context) {
    if (_nextNumber == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('New LR')),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                title: 'Could not start a new LR',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _loadDefaults,
              ),
      );
    }
    final text = Theme.of(context).textTheme;
    final muted = StatusColors.of(context).muted;
    return FormPage(
      title: 'New LR',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Preview',
      onSubmit: () => submit(_preview),
      children: [
        OutlinedButton.icon(
          onPressed: _scanning ? null : _scanInvoice,
          icon: const Icon(Icons.document_scanner_outlined),
          label: Text(_scanning ? 'Reading the invoice…' : 'Scan invoice'),
        ),
        const SizedBox(height: 8),
        _section('Booking'),
        AppCard(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('LR number $_nextNumber', style: text.titleMedium),
                const SizedBox(height: 4),
                Text('Assigned for good when you print.', style: text.bodyMedium!.copyWith(color: muted)),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Date', style: text.labelMedium),
              const SizedBox(height: 8),
              AppCard(
                child: ListTile(
                  title: Text(lrDateLabel(_isoDate(_date)), style: text.bodyLarge),
                  trailing: const Icon(Icons.calendar_today_outlined, color: Palette.onSurfaceVariant),
                  onTap: _pickDate,
                ),
              ),
            ],
          ),
        ),
        _field('from', 'From', _from, mandatory: true),
        _field('to', 'To', _to, mandatory: true),
        ChoiceField<String>(
          label: 'Freight by',
          options: _freightByOptions,
          value: _freightBy,
          highlighted: _filledByApp.contains('freight_by'),
          onChanged: (v) => setState(() {
            _freightBy = v;
            _freightByChosen = true;
            _filledByApp.remove('freight_by');
          }),
        ),
        _section('Parties'),
        Focus(
          onFocusChange: (hasFocus) {
            if (!hasFocus) _suggestFromLastLr();
          },
          child: Column(
            children: [
              _field('consignor', 'Consignor', _consignor, mandatory: true),
              _field('consignor_gstin', 'Consignor GST No', _consignorGstin),
            ],
          ),
        ),
        _field('consignee', 'Consignee', _consignee, mandatory: true),
        _field('consignee_gstin', 'Consignee GST No', _consigneeGstin),
        _section('Goods'),
        _field('goods', 'Description', _goods, mandatory: true),
        _field(
          'packages',
          'Packages',
          _packages,
          mandatory: true,
          check: _checkWholeNumber,
          keyboardType: TextInputType.number,
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Package type (optional)', style: text.labelMedium),
              const SizedBox(height: 8),
              AppCard(
                child: ListTile(
                  title: Text(
                    _itemTypes.where((t) => t['id'] == _itemTypeId).map((t) => t['name'] as String).firstOrNull ??
                        'Not set',
                    style: text.bodyLarge,
                  ),
                  subtitle: Text(
                    _filledByApp.contains('item_type')
                        ? 'Filled in for you. Check it.'
                        : 'Lets the load planner work out space and weight.',
                    style: text.bodySmall!.copyWith(
                      color: _filledByApp.contains('item_type') ? Palette.warning : muted,
                    ),
                  ),
                  trailing: const Icon(Icons.expand_more, color: Palette.onSurfaceVariant),
                  onTap: _pickItemType,
                ),
              ),
            ],
          ),
        ),
        _number('weight', 'Weight', _weight),
        _number('charged_weight', 'Charged weight', _chargedWeight),
        _number('value', 'Value', _value),
        _field('eway_bill', 'E-way bill number', _ewayBill, check: _checkEwayBill, keyboardType: TextInputType.number),
        _section('Charges'),
        _number('rate', 'Rate', _rate),
        _number('freight', 'Freight', _freight),
        _number('hamali', 'Hamali', _hamali),
        _number('other_charges', 'Other charges', _otherCharges),
        _number('st_charges', 'ST. charges', _stCharges),
        AppCard(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: ListenableBuilder(
              listenable: Listenable.merge(_charges),
              builder: (_, __) => Row(
                children: [
                  Expanded(child: Text('Total', style: text.titleMedium)),
                  Text(_total.toStringAsFixed(2), style: text.titleMedium),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 16),
      ],
    );
  }
}

/// The LR as it will print. Confirming saves it with its final number and opens the print dialog.
/// Going back changes nothing. Pops with `true` once saved.
class LrConfirmScreen extends StatefulWidget {
  const LrConfirmScreen({super.key, required this.preview, required this.fields});

  final Uint8List preview;
  final Map<String, dynamic> fields;

  @override
  State<LrConfirmScreen> createState() => _LrConfirmScreenState();
}

class _LrConfirmScreenState extends State<LrConfirmScreen> {
  bool _busy = false;
  String? _error;

  Future<void> _confirmAndPrint() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = context.read<ApiClient>();
    final messenger = ScaffoldMessenger.of(context);
    final Map<String, dynamic> lr;
    try {
      lr = await api.post('/lrs', widget.fields) as Map<String, dynamic>;
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e.message;
        });
      }
      return;
    }
    // Saved from here on: whatever happens with the printer, leave this screen.
    final number = lr['lr_number'] as String;
    try {
      final pdf = await api.getBytes('/lrs/${lr['id']}/pdf');
      await Printing.layoutPdf(onLayout: (_) async => pdf, name: 'LR-$number', format: lrPageFormat);
      messenger.showSnackBar(SnackBar(content: Text('LR $number saved.')));
    } on ApiException {
      messenger.showSnackBar(
        SnackBar(content: Text('LR $number saved, but printing failed. Print it again from the LR list.')),
      );
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Check the LR')),
        body: SafeArea(
          child: Column(
            children: [
              Expanded(
                child: PdfPreview(
                  build: (_) async => widget.preview,
                  initialPageFormat: lrPageFormat,
                  useActions: false,
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    if (_error != null) ...[ErrorBanner(_error!), const SizedBox(height: 12)],
                    FilledButton(
                      onPressed: _busy ? null : _confirmAndPrint,
                      child: _busy
                          ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Confirm and print'),
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: _busy ? null : () => Navigator.of(context).pop(),
                      child: const Text('Back to edit'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
