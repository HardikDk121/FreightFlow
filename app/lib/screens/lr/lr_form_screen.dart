import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../format.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../validation.dart';
import '../../widgets/common.dart';
import '../../widgets/suggest_field.dart';
import 'lr_page.dart';

const _freightByOptions = {'ToPay': 'To pay', 'Paid': 'Paid', 'TBB': 'To be billed'};
const _categoryOptions = {
  'regular': 'Regular goods',
  'job_work': 'For job work',
  'handicraft': 'Handicraft, exempt dealer',
  'household_effects': 'Used household effects',
  'exempt_goods': 'Exempt goods',
};
const _legOptions = {
  'direct': 'Straight to consignee',
  'consignor_to_hub': 'Consignor to our hub',
  'hub_to_consignee': 'Our hub to consignee',
};
final _pan = RegExp(r'^[A-Z]{5}[0-9]{4}[A-Z]$');
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
  const LrFormScreen({super.key, this.startWithScan = false});

  /// Open the camera as soon as the form is ready, for Home's "Scan invoice".
  final bool startWithScan;

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
  final _weightPerPackage = TextEditingController();
  final _weight = TextEditingController();
  final _chargedWeight = TextEditingController();
  final _rate = TextEditingController();
  final _freight = TextEditingController();
  final _hamali = TextEditingController();
  final _otherCharges = TextEditingController();
  final _stCharges = TextEditingController();
  final _value = TextEditingController();
  final _ewayBill = TextEditingController();
  final _distance = TextEditingController();
  final _hsn = TextEditingController();
  final _consignorPan = TextEditingController();
  final _consigneePan = TextEditingController();
  final _enrolmentId = TextEditingController();

  // E-way bill inputs. States are two-digit GST state codes.
  List<Map<String, dynamic>> _states = const [];
  String? _fromState;
  String? _toState;
  final Set<String> _statesChosen = {};
  String _category = 'regular';
  String _leg = 'direct';

  // Rate matrix. With a class of goods chosen, the server prices the freight from the matrix;
  // with none, freight is rate x charged weight.
  List<String> _goodsClasses = const [];
  String _goodsClass = '';

  /// With no class of goods chosen: freight is rate x chargeable weight, or rate x articles.
  String _basis = 'per_kg';
  String? _rateRuleId;
  String? _quoteProblem;
  Timer? _quoteDebounce;

  /// The customer's contract rate for this destination, when they have one; shown above the rate.
  Map<String, dynamic>? _contract;
  Timer? _contractDebounce;
  int _contractRequest = 0;

  /// After the payer or destination changes, look for a contract rate and use it unless the
  /// rate was typed by hand. The server checks nothing here: an LR may still be charged differently,
  /// and Analytics lists those.
  void _scheduleContract() {
    _contractDebounce?.cancel();
    _contractDebounce = Timer(const Duration(milliseconds: 500), _checkContract);
  }

  Future<void> _checkContract() async {
    final payer = (_freightBy == 'ToPay' ? _consignee : _consignor).text.trim();
    final city = _to.text.trim();
    if (payer.isEmpty || city.isEmpty) {
      if (_contract != null) setState(() => _contract = null);
      return;
    }
    final request = ++_contractRequest;
    try {
      final found = await context.read<ApiClient>().get('/contracts/rate', query: {'party': payer, 'destination': city}) as Map<String, dynamic>?;
      if (!mounted || request != _contractRequest) return;
      setState(() {
        _contract = found;
        if (found != null && _goodsClass.isEmpty && !_typed.contains('rate')) {
          _basis = found['basis'] as String;
          _rate.text = found['rate'] as String;
          _filledByApp.add('rate');
          _recalculate();
        }
      });
    } on ApiException {
      // Without the lookup the clerk enters the rate as usual.
    }
  }
  int _quoteRequest = 0;

  /// The server's answer on whether an e-way bill is needed, refreshed as the inputs change.
  Map<String, dynamic>? _requirement;
  Timer? _evaluateDebounce;
  int _evaluateRequest = 0;
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
    for (final c in [_consignor, _consignee, _to]) {
      c.addListener(_scheduleContract);
    }
  }

  @override
  void dispose() {
    for (final c in [
      _from, _to, _consignor, _consignorGstin, _consignee, _consigneeGstin, _goods, _packages, _weight,
      _chargedWeight, _rate, _freight, _hamali, _otherCharges, _stCharges, _value, _ewayBill,
      _distance, _hsn, _consignorPan, _consigneePan, _enrolmentId, _weightPerPackage,
    ]) {
      c.dispose();
    }
    _evaluateDebounce?.cancel();
    _quoteDebounce?.cancel();
    _contractDebounce?.cancel();
    super.dispose();
  }

  Map<String, dynamic>? get _itemType => _itemTypes.where((t) => t['id'] == _itemTypeId).firstOrNull;

  Future<void> _loadDefaults() async {
    setState(() => _loadError = null);
    try {
      final api = context.read<ApiClient>();
      final defaults = await api.get('/lrs/defaults') as Map<String, dynamic>;
      final itemTypes = await api.get('/item-types', query: {'limit': '200'}) as List;
      final states = await api.get('/eway/states') as List;
      final classes = await api.get('/rates/classes') as List;
      if (!mounted) return;
      setState(() {
        _goodsClasses = classes.cast<String>();
        _states = states.cast<Map<String, dynamic>>();
        _itemTypes = itemTypes.cast<Map<String, dynamic>>();
        _nextNumber = defaults['next_lr_number'] as String;
        _fill('from', _from, defaults['from_city'] as String?);
        final st = double.parse(defaults['st_charges'] as String);
        if (st > 0) _fill('st_charges', _stCharges, st.toStringAsFixed(2));
      });
      if (widget.startWithScan) WidgetsBinding.instance.addPostFrameCallback((_) => _scanInvoice());
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

  /// Re-run the calculations. Call inside setState after any input changes.
  ///   weight per package = the package type's unit weight
  ///   weight             = packages x weight per package
  ///   charged weight     = weight
  ///   freight            = rate x charged weight (when no class of goods is chosen)
  void _recalculate() {
    final packages = int.tryParse(_packages.text.trim());
    final unit = _itemType?['unit_weight_kg'] as num?;
    if (unit != null) {
      _calculate('weight_per_package', _weightPerPackage, _plain(unit), 'From the package type');
    }
    final each = double.tryParse(_weightPerPackage.text.trim());
    if (packages != null && packages > 0 && each != null && each > 0) {
      _calculate('weight', _weight, _plain(packages * each), '$packages packages × ${_plain(each)} kg each');
    }
    final weight = double.tryParse(_weight.text.trim());
    if (weight != null && weight > 0) {
      _calculate('charged_weight', _chargedWeight, _plain(weight), 'Same as the weight');
    }
    if (_goodsClass.isNotEmpty) return; // the rate matrix prices it; see _quote
    // Freight is never typed: the server checks it equals rate x quantity, so it is always worked out.
    final rate = double.tryParse(_rate.text.trim());
    final quantity = _basis == 'per_kg'
        ? double.tryParse(_chargedWeight.text.trim())
        : int.tryParse(_packages.text.trim())?.toDouble();
    if (rate != null && rate > 0 && quantity != null && quantity > 0) {
      _freight.text = (rate * quantity).toStringAsFixed(2);
      _freightWorking = _basis == 'per_kg'
          ? '${_plain(quantity)} kg × ₹${_plain(rate)} per kg'
          : '${quantity.toInt()} articles × ₹${_plain(rate)} per article';
    } else {
      _freight.clear();
      _freightWorking = _basis == 'per_kg' ? 'Enter the rate per kg.' : 'Enter the rate per article.';
    }
  }

  /// How the freight shown was worked out, under the freight figure.
  String _freightWorking = 'Enter the rate per kg.';

  /// Ask the server to price the freight from the rate matrix, once typing pauses.
  void _scheduleQuote() {
    _quoteDebounce?.cancel();
    if (_goodsClass.isEmpty) return;
    _quoteDebounce = Timer(const Duration(milliseconds: 400), _quote);
  }

  Future<void> _quote() async {
    final packages = int.tryParse(_packages.text.trim());
    final city = _to.text.trim();
    if (packages == null || packages < 1 || city.isEmpty) return;
    final request = ++_quoteRequest;
    final each = double.tryParse(_weightPerPackage.text.trim());
    // A total the person typed overrides packages x weight per package.
    final typedTotal = _typed.contains('charged_weight')
        ? _chargedWeight.text.trim()
        : _typed.contains('weight')
            ? _weight.text.trim()
            : null;
    try {
      final q = await context.read<ApiClient>().post('/rates/quote', {
        'goods_class': _goodsClass,
        'to_city': city,
        'packages': packages,
        if (each != null && each > 0) 'weight_per_package': _weightPerPackage.text.trim(),
        if (typedTotal != null && (double.tryParse(typedTotal) ?? 0) > 0) 'total_weight': typedTotal,
      }) as Map<String, dynamic>;
      if (!mounted || request != _quoteRequest) return;
      setState(() {
        _quoteProblem = null;
        _rateRuleId = q['rate_rule_id'] as String;
        final working = (q['explanation'] as List).cast<String>();
        _freight.text = q['freight'] as String;
        _freightWorking = working.skip(1).join('. ');
        final perKg = q['rate_per_kg'] as String?;
        if (perKg != null) _calculate('rate', _rate, perKg, working.first);
      });
    } on ApiException catch (e) {
      if (!mounted || request != _quoteRequest) return;
      setState(() {
        _quoteProblem = e.message;
        _rateRuleId = null;
      });
    }
  }

  /// The person typed in a field: it is theirs now, and anything calculated from it updates.
  void _onTyped(String key, String text) => setState(() {
        _filledByApp.remove(key);
        _calculated.remove(key);
        // Clearing a field hands it back to the calculation.
        text.trim().isEmpty ? _typed.remove(key) : _typed.add(key);
        _recalculate();
        _refreshEway();
      });

  String? _stateName(String? code) =>
      _states.where((s) => s['code'] == code).map((s) => s['name'] as String).firstOrNull;

  /// Call inside setState after anything the e-way bill decision depends on has changed.
  /// A GST number starts with its state code, so the states follow the GST numbers until
  /// the person picks a state themselves. Then the decision is asked for again.
  void _refreshEway() {
    void follow(String key, TextEditingController gstin, void Function(String code) set) {
      final text = gstin.text.trim().toUpperCase();
      if (_statesChosen.contains(key) || !_gstin.hasMatch(text) || _stateName(text.substring(0, 2)) == null) return;
      set(text.substring(0, 2));
      _filledByApp.add(key);
    }

    follow('from_state', _consignorGstin, (code) => _fromState = code);
    follow('to_state', _consigneeGstin, (code) => _toState = code);
    _scheduleQuote();
    _evaluateDebounce?.cancel();
    _evaluateDebounce = Timer(const Duration(milliseconds: 400), _evaluate);
  }

  Future<void> _evaluate() async {
    if (_fromState == null || _toState == null) return;
    final request = ++_evaluateRequest;
    // Only a valid goods value is sent. Blank or invalid ("-0000") gets "goods value needed", never
    // a definite "no e-way bill needed".
    final value = _checkAboveZero(_value.text.trim()) == null ? number(_value.text) : null;
    final distance = int.tryParse(_distance.text.trim());
    try {
      final result = await context.read<ApiClient>().post('/eway/evaluate', {
        if (value != null) 'value': normalizeNumber(_value.text),
        'from_state': _fromState,
        'to_state': _toState,
        'category': _category,
        'consignor_registered': _gstin.hasMatch(_consignorGstin.text.trim().toUpperCase()),
        'consignee_registered': _gstin.hasMatch(_consigneeGstin.text.trim().toUpperCase()),
        if (distance != null && distance > 0 && distance <= 4000) 'distance_km': distance,
        'leg': _leg,
      }) as Map<String, dynamic>;
      // A newer check may have started while this one was in flight.
      if (mounted && request == _evaluateRequest) setState(() => _requirement = result);
    } on ApiException {
      // The decision is advice on this screen; the server decides again when the LR is saved.
    }
  }

  Future<void> _pickState(String key) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      backgroundColor: Palette.surface,
      builder: (sheet) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(sheet).height * 0.7,
          child: ListView(
            children: [
              for (final state in _states)
                ListTile(
                  title: Text(state['name'] as String),
                  trailing: Text(state['code'] as String),
                  onTap: () => Navigator.of(sheet).pop(state['code'] as String),
                ),
            ],
          ),
        ),
      ),
    );
    if (picked == null) return;
    setState(() {
      key == 'from_state' ? _fromState = picked : _toState = picked;
      _statesChosen.add(key);
      _filledByApp.remove(key);
      _refreshEway();
    });
  }

  Widget _stateField(String key, String label, String? code) => PickerField(
        label: label,
        value: _stateName(code),
        placeholder: 'Choose',
        onTap: () => _pickState(key),
        note: _filledByApp.contains(key) ? 'From the GST number. Check it.' : null,
        noteTone: Tone.info,
      );


  /// The e-way bill decision, in words: needed or not, why, who generates it, how long it lasts.
  Widget _requirementCard() {
    final text = Theme.of(context).textTheme;
    final r = _requirement;
    if (r == null) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Text(
          'Choose both states to see whether this LR needs an e-way bill.',
          style: text.bodyMedium!.copyWith(color: StatusColors.of(context).muted),
        ),
      );
    }
    final required = r['required'] as bool?;
    final (label, background, foreground) = switch (required) {
      true => ('E-way bill needed', Palette.warningContainer, Palette.warning),
      false => ('No e-way bill needed', Palette.successContainer, Palette.success),
      null => ('Goods value needed', Palette.primaryContainer, Palette.onPrimaryContainer),
    };
    final days = r['validity_days'] as int?;
    final lines = [
      '${r['reason']} (${r['rule']})',
      if (r['responsible'] != null) 'Generated by the ${r['responsible']}.',
      if (days != null) 'Valid for $days day${days == 1 ? '' : 's'} once the vehicle is entered.',
      if (required == true && days == null) 'Enter the distance to see how long it stays valid.',
      for (final note in (r['notes'] as List).cast<String>()) note,
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(16)),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: text.titleMedium!.copyWith(color: foreground)),
            const SizedBox(height: 6),
            for (final line in lines)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(line, style: text.bodyMedium!.copyWith(color: foreground)),
              ),
          ],
        ),
      ),
    );
  }

  static String? _checkPan(String value) => _pan.hasMatch(value.toUpperCase()) ? null : 'A PAN looks like ABCDE1234F';

  static String? _checkDistance(String value) {
    final n = int.tryParse(value);
    return n == null || n < 1 || n > 4000 ? 'Whole km, 1 to 4000' : null;
  }

  static String? _checkHsn(String value) => hsnCode(value);

  static String? _checkEnrolment(String value) => enrolmentId(value);

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
        _refreshEway();
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
      final scan = await api.postFile('/invoices/scan', await photo.readAsBytes(), photo.name) as Map<String, dynamic>;
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
        _fill('hsn', _hsn, scan['hsn_code'] as String?);
        _refreshEway();
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
    final n = number(value);
    if (n == null) return 'Enter a number';
    if (n <= 0) return 'Must be more than 0';
    final decimals = value.contains('.') ? value.trim().split('.').last.length : 0;
    return decimals > 2 ? 'Use at most 2 decimal places' : null;
  }

  static String? _checkRate(String value) {
    final n = double.tryParse(value);
    if (n == null) return 'Enter a number';
    return n <= 0 ? 'Rate cannot be 0. Leave it blank if there is no rate.' : null;
  }

  static String? _checkPackages(String value) {
    final n = int.tryParse(value.trim());
    if (n == null || n < 1) return 'Enter a whole number, 1 or more';
    return n > 99999 ? 'Must be at most 99999' : null;
  }

  static String? _checkGstin(String value) => gstin(value);

  static String? _checkEwayBill(String value) => ewayBillNumber(value);

  String? _checkTo(String value) =>
      city(value) ?? (tidy(value).toUpperCase() == tidy(_from.text).toUpperCase() ? 'From and To cannot be the same' : null);

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
      'from_city': tidy(_from.text).toUpperCase(),
      'to_city': tidy(_to.text).toUpperCase(),
      'freight_by': _freightBy,
      'consignor_name': tidy(_consignor.text),
      'consignee_name': tidy(_consignee.text),
      'goods_description': _goods.text.trim(),
      'packages': int.parse(_packages.text.trim()),
      'weight': normalizeNumber(_weight.text),
    };
    if (_goodsClass.isNotEmpty && _rateRuleId != null) body['rate_rule_id'] = _rateRuleId;
    body['charge_basis'] = _goodsClass.isNotEmpty ? 'matrix' : _basis;
    final optional = {
      'consignor_gstin': _consignorGstin,
      'consignee_gstin': _consigneeGstin,
      'weight_per_package': _weightPerPackage,
      'charged_weight': _chargedWeight,
      'rate': _rate,
      'freight': _freight,
      'hamali': _hamali,
      'other_charges': _otherCharges,
      'st_charges': _stCharges,
      'value': _value,
      'eway_bill_no': _ewayBill,
    };
    const numbers = {'weight_per_package', 'charged_weight', 'rate', 'freight', 'hamali', 'other_charges', 'st_charges', 'value'};
    for (final entry in optional.entries) {
      final text = entry.value.text.trim();
      // ".5" goes as "0.5"; codes go without spaces and in capitals.
      if (text.isNotEmpty) body[entry.key] = numbers.contains(entry.key) ? normalizeNumber(text) : text.replaceAll(' ', '').toUpperCase();
    }
    if (_itemTypeId != null) body['item_type_id'] = _itemTypeId;
    body.addAll({'from_state': _fromState, 'to_state': _toState, 'goods_category': _category, 'trip_leg': _leg});
    final distance = _distance.text.trim();
    if (distance.isNotEmpty) body['distance_km'] = int.parse(distance);
    final upper = {
      'hsn_code': _hsn,
      'consignor_pan': _consignorPan,
      'consignee_pan': _consigneePan,
      'enrolment_id': _enrolmentId,
    };
    for (final entry in upper.entries) {
      final text = entry.value.text.trim().toUpperCase();
      if (text.isNotEmpty) body[entry.key] = text;
    }
    return body;
  }

  /// The LR as it would print, to look at or share before anything is saved.
  Future<void> _draftPdf() async {
    if (_fromState == null || _toState == null) {
      throw const ApiException(0, 'Choose the From state and the To state in the e-way bill section.');
    }
    final pdf = await context
        .read<ApiClient>()
        .postForBytes('/lrs/print-preview', {..._fields(), 'lr_number': _nextNumber!});
    if (!mounted) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => Scaffold(
          appBar: AppBar(title: const Text('Draft preview')),
          body: PdfPreview(
            build: (_) async => pdf,
            initialPageFormat: lrPageFormat,
            canChangePageFormat: false,
            canChangeOrientation: false,
            canDebug: false,
            allowPrinting: false,
            pdfFileName: 'LR-draft.pdf',
          ),
        ),
      ),
    );
  }

  Future<void> _preview() async {
    if (_fromState == null || _toState == null) {
      throw const ApiException(0, 'Choose the From state and the To state in the e-way bill section.');
    }
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

  /// A party name with autocomplete from past LRs and the party master. Picking one fills its
  /// GST number (and, for a consignee, the destination) where those are still empty.
  Widget _party(String role, String label, TextEditingController controller) => SuggestField(
        label: label,
        controller: controller,
        mandatory: true,
        check: (v) => v.trim().length > 60 ? 'Use at most 60 characters.' : businessName(v),
        highlighted: _filledByApp.contains(role),
        search: (query) async {
          final rows = await context.read<ApiClient>().get('/lrs/parties', query: {'q': query, 'role': role});
          return (rows as List).cast<Map<String, dynamic>>();
        },
        titleOf: (row) => row['name'] as String,
        subtitleOf: (row) => [row['gstin'], row['city']].whereType<String>().join(' · '),
        onChanged: (text) => _onTyped(role, text),
        onPicked: (row) {
          setState(() {
            _typed.add(role);
            _filledByApp.remove(role);
            if (role == 'consignor') {
              _fill('consignor_gstin', _consignorGstin, row['gstin'] as String?);
            } else {
              _fill('consignee_gstin', _consigneeGstin, row['gstin'] as String?);
              _fill('to', _to, (row['city'] as String?)?.toUpperCase());
            }
            _refreshEway();
          });
          if (role == 'consignor') _suggestFromLastLr();
        },
      );

  /// Two short fields side by side.
  Widget _pair(Widget left, Widget right) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [Expanded(child: left), const SizedBox(width: 12), Expanded(child: right)],
      );

  Widget _scanCard() {
    final text = Theme.of(context).textTheme;
    return AppCard(
      onTap: _scanning ? null : _scanInvoice,
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: const BoxDecoration(color: Palette.primary, shape: BoxShape.circle),
            child: _scanning
                ? const Padding(
                    padding: EdgeInsets.all(13),
                    child: CircularProgressIndicator(strokeWidth: 2.5, color: Palette.onPrimary),
                  )
                : const Icon(Icons.document_scanner_outlined, color: Palette.onPrimary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(_scanning ? 'Reading the invoice…' : 'Scan the invoice', style: text.titleMedium),
                const SizedBox(height: 2),
                Text(
                  'Fills the parties, goods, value and e-way bill for you.',
                  style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
        ],
      ),
    );
  }

  /// The dark header: title, the provisional number, and the route, which is what the clerk sets first.
  Widget _hero() => HeroHeader(
        showBack: true,
        trailing: StatusChip.tone('DRAFT · $_nextNumber', Tone.dark),
        title: 'New lorry receipt',
        eyebrow: 'Route',
        subtitle: 'The LR number is fixed when you print.',
        child: AppCard(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
          child: Column(
            children: [
              _field('from', 'From', _from, mandatory: true, check: city),
              _field('to', 'To', _to, mandatory: true, check: _checkTo),
            ],
          ),
        ),
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
    final itemTypeFilled = _filledByApp.contains('item_type');
    // With no GST number on either side, the PAN of both is needed.
    final bothUnregistered = _consignorGstin.text.trim().isEmpty && _consigneeGstin.text.trim().isEmpty;
    return FormPage(
      title: 'New lorry receipt',
      hero: _hero(),
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Review & print',
      onSubmit: () => submit(_preview),
      secondaryLabel: 'Draft PDF',
      onSecondary: () => submit(_draftPdf),
      footer: ListenableBuilder(
        listenable: Listenable.merge(_charges),
        builder: (_, __) => Row(
          children: [
            Expanded(child: Text('Total to collect', style: text.bodyMedium!.copyWith(color: muted))),
            Text(rupees(_total), style: text.titleLarge),
          ],
        ),
      ),
      children: [
        _scanCard(),
        const SectionHeader('Booking', icon: Icons.event_note_outlined),
        PickerField(
          label: 'Booking date',
          value: lrDateLabel(_isoDate(_date)),
          placeholder: 'Choose a date',
          icon: Icons.calendar_today_outlined,
          onTap: _pickDate,
        ),
        ChoiceField<String>(
          label: 'Freight by',
          options: _freightByOptions,
          value: _freightBy,
          highlighted: _filledByApp.contains('freight_by'),
          onChanged: (v) {
            setState(() {
              _freightBy = v;
              _freightByChosen = true;
              _filledByApp.remove('freight_by');
            });
            _scheduleContract();
          },
        ),
        const SectionHeader('Parties', icon: Icons.groups_outlined),
        Focus(
          onFocusChange: (hasFocus) {
            if (!hasFocus) _suggestFromLastLr();
          },
          child: Column(
            children: [
              _party('consignor', 'Consignor', _consignor),
              _field('consignor_gstin', 'Consignor GST No', _consignorGstin, check: _checkGstin),
              if (_consignorGstin.text.trim().isEmpty)
                _field('consignor_pan', 'Consignor PAN', _consignorPan, mandatory: bothUnregistered, check: _checkPan),
            ],
          ),
        ),
        _party('consignee', 'Consignee', _consignee),
        _field('consignee_gstin', 'Consignee GST No', _consigneeGstin, check: _checkConsigneeGstin),
        if (_consigneeGstin.text.trim().isEmpty)
          _field('consignee_pan', 'Consignee PAN', _consigneePan, mandatory: bothUnregistered, check: _checkPan),
        const SectionHeader('Goods', icon: Icons.inventory_2_outlined),
        _field('goods', 'Description', _goods, mandatory: true),
        PickerField(
          label: 'Package type',
          mandatory: false,
          value: _itemType?['name'] as String?,
          placeholder: 'Not set',
          onTap: _pickItemType,
          note: itemTypeFilled
              ? 'Filled in for you. Check it.'
              : 'Works out the weight from the packages, and helps plan truck loads.',
          noteTone: itemTypeFilled ? Tone.info : Tone.neutral,
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
          _number('weight_per_package', 'Weight per package', _weightPerPackage, check: _checkAboveZero, unit: 'kg'),
        ),
        _pair(
          _number('weight', 'Total weight', _weight, mandatory: true, check: _checkAboveZero, unit: 'kg'),
          _number('charged_weight', 'Charged weight', _chargedWeight, check: _checkChargedWeight, unit: 'kg'),
        ),
        _pair(
          _number('value', 'Goods value', _value, check: _checkAboveZero, unit: 'Rs'),
          _field('hsn', 'HSN code', _hsn, check: _checkHsn, keyboardType: TextInputType.number),
        ),
        const SectionHeader('E-way bill', icon: Icons.verified_outlined),
        _pair(
          _stateField('from_state', 'From state', _fromState),
          _stateField('to_state', 'To state', _toState),
        ),
        ChoiceField<String>(
          label: 'What is being moved',
          options: _categoryOptions,
          value: _category,
          onChanged: (v) => setState(() {
            _category = v;
            _refreshEway();
          }),
        ),
        ChoiceField<String>(
          label: 'This trip goes',
          options: _legOptions,
          value: _leg,
          onChanged: (v) => setState(() {
            _leg = v;
            _refreshEway();
          }),
        ),
        _field(
          'distance',
          'Distance',
          _distance,
          check: _checkDistance,
          keyboardType: TextInputType.number,
          unit: 'km',
        ),
        _requirementCard(),
        AppTextField(
          label: 'E-way bill number',
          controller: _ewayBill,
          check: _checkEwayBill,
          keyboardType: TextInputType.number,
          highlighted: _filledByApp.contains('eway_bill'),
          helper: 'If it is not generated yet, add it later from the saved LR, before dispatch.',
          onChanged: (text) => _onTyped('eway_bill', text),
        ),
        if (bothUnregistered)
          _field('enrolment_id', 'Sender enrolment ID (ENR-03)', _enrolmentId, check: _checkEnrolment),
        const SectionHeader('Charges', icon: Icons.payments_outlined),
        if (_goodsClasses.isNotEmpty)
          ChoiceField<String>(
            label: 'Charge as',
            options: {'': 'My own rate', for (final c in _goodsClasses) c: c},
            value: _goodsClass,
            onChanged: (v) => setState(() {
              _goodsClass = v;
              _quoteProblem = null;
              _rateRuleId = null;
              // Hand the rate and freight back to whichever method now applies.
              if (_calculated.remove('rate') != null) _rate.clear();
              _freight.clear();
              _recalculate();
              _scheduleQuote();
            }),
          ),
        if (_quoteProblem != null)
          Padding(padding: const EdgeInsets.only(bottom: 16), child: ErrorBanner(_quoteProblem!)),
        if (_contract != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: AppCard(
              color: Palette.primaryContainer,
              padding: const EdgeInsets.all(14),
              child: Text(
                'Contract rate for ${_contract!['party_name']}: ₹${_contract!['rate']} per ${_contract!['basis'] == 'per_kg' ? 'kg' : 'article'}, '
                'until ${dayLabel(_contract!['ends_on'] as String)}.',
                style: text.bodyMedium!.copyWith(color: Palette.onPrimaryContainer),
              ),
            ),
          ),
        if (_goodsClass.isEmpty)
          ChoiceField<String>(
            label: 'Charge by',
            options: const {'per_kg': 'Per kg', 'per_article': 'Per article'},
            value: _basis,
            onChanged: (v) => setState(() {
              _basis = v;
              _recalculate();
            }),
          ),
        _number(
          'rate',
          _basis == 'per_article' && _goodsClass.isEmpty ? 'Rate per article' : 'Rate per kg',
          _rate,
          check: _checkRate,
          unit: 'Rs',
        ),
        // The freight, worked out, with how.
        ListenableBuilder(
          listenable: _freight,
          builder: (_, __) => Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: AppCard(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Freight', style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant)),
                        const SizedBox(height: 2),
                        Text(_freightWorking, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
                      ],
                    ),
                  ),
                  Text(rupees(double.tryParse(_freight.text) ?? 0), style: text.titleLarge),
                ],
              ),
            ),
          ),
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

  /// One key for this LR, however many times saving is retried, so it is booked once.
  final _key = newIdempotencyKey();

  /// Set when the owner books for a customer on hold, with the reason they gave.
  String? _override;

  Future<void> _askOverride(String message) async {
    final reason = await showDialog<String>(context: context, builder: (_) => _OverrideDialog(message: message));
    if (reason == null || !mounted) return;
    _override = reason;
    await _confirmAndPrint();
  }

  Future<void> _confirmAndPrint() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = context.read<ApiClient>();
    final messenger = ScaffoldMessenger.of(context);
    final Map<String, dynamic> lr;
    try {
      lr = await api.post(
        '/lrs',
        {...widget.fields, if (_override != null) 'credit_override_reason': _override},
        idempotencyKey: _key,
      ) as Map<String, dynamic>;
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.message;
      });
      final isOwner = context.read<Session>().user?.can('credit.override') ?? false;
      if (e.code == 'credit_hold' && isOwner && _override == null) await _askOverride(e.message);
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


/// The owner books for a customer on hold anyway, saying why. The reason is kept on the LR.
class _OverrideDialog extends StatefulWidget {
  const _OverrideDialog({required this.message});

  final String message;

  @override
  State<_OverrideDialog> createState() => _OverrideDialogState();
}

class _OverrideDialogState extends State<_OverrideDialog> {
  final _reason = TextEditingController();

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Book anyway?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.message),
            const SizedBox(height: 16),
            TextField(
              controller: _reason,
              autofocus: true,
              maxLength: 200,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(hintText: 'Why, for the record'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Do not book')),
          TextButton(
            onPressed: _reason.text.trim().length < 3 ? null : () => Navigator.of(context).pop(_reason.text.trim()),
            child: const Text('Book with this reason'),
          ),
        ],
      );
}
