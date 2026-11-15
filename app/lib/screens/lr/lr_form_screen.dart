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
final _gstin = RegExp(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$');

/// 500.0 -> "500", 12.5 -> "12.50".
String _plain(num value) => value == value.roundToDouble() ? value.toInt().toString() : value.toStringAsFixed(2);

/// A new LR.
///
/// Three things fill fields without typing: the company defaults, a scanned invoice, and the
/// consignor's last LR (all shown in amber until checked). Three values are calculated and
/// follow their inputs until the person types over them:
///   weight         = packages x unit weight of the package type
///   charged weight = weight
///   freight        = rate x charged weight
/// Nothing is saved until the printed preview is confirmed. Pops with `true` once saved.
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
  bool _freightByChosen = false;

  /// What one package is. Gives the weight calculation and the load planner their numbers.
  String? _itemTypeId;
  List<Map<String, dynamic>> _itemTypes = const [];
  bool _scanning = false;

  /// Provisional: the server assigns the real number when the LR is saved.
  String? _nextNumber;
  String? _loadError;

  /// Fields the app filled from defaults, a scan or the last LR, not yet checked by the person.
  final Set<String> _filledByApp = {};

  /// Fields currently holding a calculated value, with how it was worked out.
  final Map<String, String> _calculated = {};

  /// Fields the person typed in. The app never overwrites these.
  final Set<String> _typed = {};
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

  Map<String, dynamic>? get _itemType => _itemTypes.where((t) => t['id'] == _itemTypeId).firstOrNull;

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

  /// Set a calculated value, unless the person has typed their own in that field.
  void _calculate(String key, TextEditingController controller, String value, String how) {
    if (_typed.contains(key)) return;
    controller.text = value;
    _calculated[key] = how;
    _filledByApp.remove(key);
  }

  /// Re-run the three calculations. Call inside setState after any input changes.
  void _recalculate() {
    final packages = int.tryParse(_packages.text.trim());
    final unit = _itemType?['unit_weight_kg'] as num?;
    if (packages != null && packages > 0 && unit != null) {
      _calculate('weight', _weight, _plain(packages * unit), '$packages packages × ${_plain(unit)} kg each');
    }
    final weight = double.tryParse(_weight.text.trim());
    if (weight != null && weight > 0) {
      _calculate('charged_weight', _chargedWeight, _plain(weight), 'Same as the weight');
    }
    final rate = double.tryParse(_rate.text.trim());
    final charged = double.tryParse(_chargedWeight.text.trim());
    if (rate != null && rate > 0 && charged != null && charged > 0) {
      _calculate('freight', _freight, (rate * charged).toStringAsFixed(2), '${_plain(rate)} per kg × ${_plain(charged)} kg');
    }
  }

  /// The person typed in a field: it is theirs now, and anything calculated from it updates.
  void _onTyped(String key, String text) => setState(() {
        _filledByApp.remove(key);
        _calculated.remove(key);
        // Clearing a field hands it back to the calculation.
        text.trim().isEmpty ? _typed.remove(key) : _typed.add(key);
        _recalculate();
      });

  /// When the person leaves the consignor fields, reuse what this consignor's last LR had.
  Future<void> _suggestFromLastLr() async {
    final name = _consignor.text.trim();
    final gstin = _consignorGstin.text.trim();
    final key = '$name|$gstin';
    if ((name.isEmpty && gstin.isEmpty) || key == _lastSuggestedFor) return;
    _lastSuggestedFor = key;
    try {
      final s = await context.read<ApiClient>().get('/lrs/suggestions', query: {
        if (name.isNotEmpty) 'consignor_name': name,
        if (_gstin.hasMatch(gstin.toUpperCase())) 'consignor_gstin': gstin,
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
        _recalculate();
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
      backgroundColor: Palette.surface,
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
      backgroundColor: Palette.surface,
      builder: (sheet) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(title: const Text('Not set'), onTap: () => Navigator.of(sheet).pop('')),
            for (final t in _itemTypes)
              ListTile(
                title: Text(t['name'] as String),
                subtitle: Text('${_plain(t['unit_weight_kg'] as num)} kg each'),
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
      _recalculate();
    });
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked != null) setState(() => _date = picked);
  }

  // Validation. Each returns a message to show under the field, or null when the value is fine.

  static String? _checkAmount(String value) {
    final n = double.tryParse(value);
    if (n == null) return 'Enter a number';
    return n < 0 ? 'Cannot be negative' : null;
  }

  static String? _checkAboveZero(String value) {
    final n = double.tryParse(value);
    if (n == null) return 'Enter a number';
    return n <= 0 ? 'Must be more than 0' : null;
  }

  static String? _checkRate(String value) {
    final n = double.tryParse(value);
    if (n == null) return 'Enter a number';
    return n <= 0 ? 'Rate cannot be 0. Leave it blank if there is no rate.' : null;
  }

  static String? _checkPackages(String value) {
    final n = int.tryParse(value);
    return n == null || n < 1 ? 'Enter a whole number, 1 or more' : null;
  }

  static String? _checkGstin(String value) =>
      _gstin.hasMatch(value.toUpperCase()) ? null : 'A GST number has 15 characters, like 24AABCR4141H1ZQ';

  static String? _checkEwayBill(String value) =>
      RegExp(r'^[0-9]{12}$').hasMatch(value) ? null : 'An e-way bill number has 12 digits';

  String? _checkTo(String value) =>
      value.toUpperCase() == _from.text.trim().toUpperCase() ? 'From and To cannot be the same' : null;

  String? _checkConsigneeGstin(String value) => value.toUpperCase() == _consignorGstin.text.trim().toUpperCase()
      ? 'Same as the consignor GST number'
      : _checkGstin(value);

  String? _checkChargedWeight(String value) {
    final problem = _checkAboveZero(value);
    if (problem != null) return problem;
    final weight = double.tryParse(_weight.text.trim());
    return weight != null && double.parse(value) < weight ? 'Cannot be less than the weight' : null;
  }

  static String _isoDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  double get _total => _charges.fold(0, (sum, c) => sum + (double.tryParse(c.text.trim()) ?? 0));

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
      'weight': _weight.text.trim(),
    };
    final optional = {
      'consignor_gstin': _consignorGstin,
      'consignee_gstin': _consigneeGstin,
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
    String? unit,
  }) =>
      AppTextField(
        label: label,
        controller: controller,
        mandatory: mandatory,
        check: check,
        keyboardType: keyboardType,
        capitalization: capitalization,
        unit: unit,
        highlighted: _filledByApp.contains(key),
        helper: _calculated[key],
        onChanged: (text) => _onTyped(key, text),
      );

  AppTextField _number(
    String key,
    String label,
    TextEditingController controller, {
    bool mandatory = false,
    String? Function(String) check = _checkAmount,
    String? unit,
  }) =>
      _field(
        key,
        label,
        controller,
        mandatory: mandatory,
        check: check,
        unit: unit,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
      );

  /// Two short fields side by side.
  Widget _pair(Widget left, Widget right) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [Expanded(child: left), const SizedBox(width: 12), Expanded(child: right)],
      );

  Widget _scanCard() {
    final text = Theme.of(context).textTheme;
    return Material(
      color: Palette.primary,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: _scanning ? null : _scanInvoice,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              _scanning
                  ? const SizedBox.square(
                      dimension: 28,
                      child: CircularProgressIndicator(strokeWidth: 2.5, color: Palette.onPrimary),
                    )
                  : const Icon(Icons.document_scanner_outlined, color: Palette.onPrimary, size: 28),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _scanning ? 'Reading the invoice…' : 'Scan the invoice',
                      style: text.titleMedium!.copyWith(color: Palette.onPrimary),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Fills the parties, goods, value and e-way bill for you.',
                      style: text.bodyMedium!.copyWith(color: Palette.onPrimary),
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
    final itemTypeFilled = _filledByApp.contains('item_type');
    return FormPage(
      title: 'New LR $_nextNumber',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Preview',
      onSubmit: () => submit(_preview),
      footer: ListenableBuilder(
        listenable: Listenable.merge(_charges),
        builder: (_, __) => Row(
          children: [
            Expanded(child: Text('Total to collect', style: text.bodyMedium!.copyWith(color: muted))),
            Text('Rs ${_total.toStringAsFixed(2)}', style: text.titleLarge),
          ],
        ),
      ),
      children: [
        _scanCard(),
        const SizedBox(height: 8),
        const SectionHeader('Booking', icon: Icons.event_note_outlined),
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
                  subtitle: Text(
                    'The LR number is fixed when you print.',
                    style: text.bodySmall!.copyWith(color: muted),
                  ),
                  trailing: const Icon(Icons.calendar_today_outlined, color: Palette.onSurfaceVariant),
                  onTap: _pickDate,
                ),
              ),
            ],
          ),
        ),
        _pair(
          _field('from', 'From', _from, mandatory: true),
          _field('to', 'To', _to, mandatory: true, check: _checkTo),
        ),
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
        const SectionHeader('Parties', icon: Icons.groups_outlined),
        Focus(
          onFocusChange: (hasFocus) {
            if (!hasFocus) _suggestFromLastLr();
          },
          child: Column(
            children: [
              _field('consignor', 'Consignor', _consignor, mandatory: true),
              _field('consignor_gstin', 'Consignor GST No', _consignorGstin, check: _checkGstin),
            ],
          ),
        ),
        _field('consignee', 'Consignee', _consignee, mandatory: true),
        _field('consignee_gstin', 'Consignee GST No', _consigneeGstin, check: _checkConsigneeGstin),
        const SectionHeader('Goods', icon: Icons.inventory_2_outlined),
        _field('goods', 'Description', _goods, mandatory: true),
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Package type (optional)', style: text.labelMedium),
              const SizedBox(height: 8),
              AppCard(
                child: ListTile(
                  title: Text(_itemType?['name'] as String? ?? 'Not set', style: text.bodyLarge),
                  subtitle: Text(
                    itemTypeFilled
                        ? 'Filled in for you. Check it.'
                        : 'Works out the weight from the packages, and helps plan truck loads.',
                    style: text.bodySmall!.copyWith(color: itemTypeFilled ? Palette.warning : muted),
                  ),
                  trailing: const Icon(Icons.expand_more, color: Palette.onSurfaceVariant),
                  onTap: _pickItemType,
                ),
              ),
            ],
          ),
        ),
        _pair(
          _field(
            'packages',
            'Packages',
            _packages,
            mandatory: true,
            check: _checkPackages,
            keyboardType: TextInputType.number,
          ),
          _number('weight', 'Weight', _weight, mandatory: true, check: _checkAboveZero, unit: 'kg'),
        ),
        _pair(
          _number('charged_weight', 'Charged weight', _chargedWeight, check: _checkChargedWeight, unit: 'kg'),
          _number('value', 'Goods value', _value, check: _checkAboveZero, unit: 'Rs'),
        ),
        _field('eway_bill', 'E-way bill number', _ewayBill, check: _checkEwayBill, keyboardType: TextInputType.number),
        const SectionHeader('Charges', icon: Icons.payments_outlined),
        _pair(
          _number('rate', 'Rate per kg', _rate, check: _checkRate, unit: 'Rs'),
          _number('freight', 'Freight', _freight, unit: 'Rs'),
        ),
        _pair(
          _number('hamali', 'Hamali', _hamali, unit: 'Rs'),
          _number('other_charges', 'Other charges', _otherCharges, unit: 'Rs'),
        ),
        _number('st_charges', 'ST. charges', _stCharges, unit: 'Rs'),
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
        body: PdfPreview(
          build: (_) async => widget.preview,
          initialPageFormat: lrPageFormat,
          useActions: false,
        ),
        bottomNavigationBar: BottomBar(
          children: [
            if (_error != null) ...[ErrorBanner(_error!), const SizedBox(height: 12)],
            FilledButton(
              onPressed: _busy ? null : _confirmAndPrint,
              child: _busy
                  ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Confirm and print'),
            ),
            TextButton(
              onPressed: _busy ? null : () => Navigator.of(context).pop(),
              child: const Text('Back to edit'),
            ),
          ],
        ),
      );
}
