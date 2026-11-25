import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../validation.dart';

/// A country for the phone field: flag, dialling code, and how a valid local number looks.
class Country {
  const Country(this.flag, this.name, this.code, this.minDigits, this.maxDigits);

  final String flag;
  final String name;
  final String code;
  final int minDigits;
  final int maxDigits;
}

/// India first; then the countries transporters most often deal with.
const countries = [
  Country('🇮🇳', 'India', '+91', 10, 10),
  Country('🇳🇵', 'Nepal', '+977', 9, 10),
  Country('🇧🇩', 'Bangladesh', '+880', 10, 10),
  Country('🇦🇪', 'UAE', '+971', 8, 9),
  Country('🇸🇦', 'Saudi Arabia', '+966', 9, 9),
  Country('🇬🇧', 'UK', '+44', 10, 10),
  Country('🇺🇸', 'USA', '+1', 10, 10),
];

/// The phone number field used on every form: a country selector (India by default) and the
/// number. For India it takes a 10-digit mobile number starting with 6 to 9; for other countries
/// it sends the number with its code. [controller] always holds what the server should receive.
class PhoneField extends StatefulWidget {
  const PhoneField({
    super.key,
    required this.controller,
    this.label = 'Phone',
    this.mandatory = false,
    this.helper,
  });

  final TextEditingController controller;
  final String label;
  final bool mandatory;
  final String? helper;

  @override
  State<PhoneField> createState() => _PhoneFieldState();
}

class _PhoneFieldState extends State<PhoneField> {
  late Country _country;
  late final TextEditingController _local;

  @override
  void initState() {
    super.initState();
    final stored = widget.controller.text.trim();
    _country = countries.first;
    var local = stored;
    if (stored.startsWith('+') && !stored.startsWith('+91')) {
      for (final c in countries.skip(1)) {
        if (stored.startsWith(c.code)) {
          _country = c;
          local = stored.substring(c.code.length);
          break;
        }
      }
    } else if (stored.startsWith('+91')) {
      local = stored.substring(3);
    }
    _local = TextEditingController(text: local)..addListener(_sync);
  }

  @override
  void dispose() {
    _local.dispose();
    super.dispose();
  }

  /// What the server receives: 10 digits for India, the code and number elsewhere, empty if blank.
  void _sync() {
    final digits = _local.text.replaceAll(RegExp(r'[^0-9]'), '');
    widget.controller.text = digits.isEmpty ? '' : (_country.code == '+91' ? digits : '${_country.code}$digits');
  }

  String? _validate(String? raw) {
    final value = raw?.trim() ?? '';
    if (value.isEmpty) return widget.mandatory ? 'Required' : null;
    if (_country.code == '+91') return indianMobile(value);
    final digits = value.replaceAll(RegExp(r'[^0-9]'), '');
    if (digits.length < _country.minDigits || digits.length > _country.maxDigits) {
      return _country.minDigits == _country.maxDigits
          ? 'Enter ${_country.minDigits} digits for ${_country.name}.'
          : 'Enter ${_country.minDigits} to ${_country.maxDigits} digits for ${_country.name}.';
    }
    return null;
  }

  Future<void> _pickCountry() async {
    final picked = await showModalBottomSheet<Country>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            for (final c in countries)
              ListTile(
                leading: Text(c.flag, style: const TextStyle(fontSize: 26)),
                title: Text(c.name),
                trailing: Text(c.code, style: Theme.of(context).textTheme.labelLarge),
                selected: c.code == _country.code,
                onTap: () => Navigator.of(context).pop(c),
              ),
          ],
        ),
      ),
    );
    if (picked != null && picked.code != _country.code) {
      setState(() => _country = picked);
      _sync();
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text.rich(
            TextSpan(
              text: widget.label,
              children: [
                if (!widget.mandatory) TextSpan(text: ' · optional', style: text.labelMedium!.copyWith(color: Palette.onSurfaceMuted)),
              ],
            ),
            style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant),
          ),
          const SizedBox(height: 6),
          TextFormField(
            controller: _local,
            keyboardType: TextInputType.phone,
            autofillHints: const [AutofillHints.telephoneNumberNational],
            autovalidateMode: AutovalidateMode.onUserInteraction,
            validator: _validate,
            decoration: InputDecoration(
              hintText: _country.code == '+91' ? '98250 11111' : null,
              helperText: widget.helper,
              prefixIcon: Semantics(
                button: true,
                label: 'Country code ${_country.name} ${_country.code}. Tap to change.',
                child: InkWell(
                  onTap: _pickCountry,
                  borderRadius: BorderRadius.circular(12),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        // The flag flips in when the country changes.
                        AnimatedSwitcher(
                          duration: const Duration(milliseconds: 220),
                          transitionBuilder: (child, animation) => ScaleTransition(
                            scale: CurvedAnimation(parent: animation, curve: Curves.easeOutBack),
                            child: FadeTransition(opacity: animation, child: child),
                          ),
                          child: Text(_country.flag, key: ValueKey(_country.code), style: const TextStyle(fontSize: 22)),
                        ),
                        const SizedBox(width: 6),
                        Text(_country.code, style: text.bodyLarge),
                        const Icon(Icons.arrow_drop_down, size: 20),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
