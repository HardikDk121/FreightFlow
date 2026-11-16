import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';
import 'common.dart';

/// A text field that looks up matches while the person types and lists them underneath.
///
/// Lookups wait until typing pauses, and only the answer to the latest lookup is shown, so a
/// slow reply never replaces a newer one. Picking a row sets this field; what else it fills is
/// up to [onPicked], which should never overwrite something the person typed.
class SuggestField extends StatefulWidget {
  const SuggestField({
    super.key,
    required this.label,
    required this.controller,
    required this.search,
    required this.titleOf,
    required this.subtitleOf,
    required this.onPicked,
    required this.onChanged,
    this.mandatory = false,
    this.highlighted = false,
  });

  final String label;
  final TextEditingController controller;
  final bool mandatory;
  final bool highlighted;
  final Future<List<Map<String, dynamic>>> Function(String query) search;
  final String Function(Map<String, dynamic> row) titleOf;
  final String Function(Map<String, dynamic> row) subtitleOf;
  final ValueChanged<Map<String, dynamic>> onPicked;
  final ValueChanged<String> onChanged;

  @override
  State<SuggestField> createState() => _SuggestFieldState();
}

class _SuggestFieldState extends State<SuggestField> {
  static const _pause = Duration(milliseconds: 300);
  static const _minLetters = 2;

  Timer? _debounce;
  int _request = 0;
  List<Map<String, dynamic>> _rows = const [];

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _typed(String text) {
    widget.onChanged(text);
    _debounce?.cancel();
    final query = text.trim();
    if (query.length < _minLetters) {
      _request++; // drop any lookup still in flight
      if (_rows.isNotEmpty) setState(() => _rows = const []);
      return;
    }
    _debounce = Timer(_pause, () => _lookUp(query));
  }

  Future<void> _lookUp(String query) async {
    final request = ++_request;
    try {
      final rows = await widget.search(query);
      if (!mounted || request != _request) return;
      // No point offering the exact text already in the field.
      final typed = widget.controller.text.trim().toLowerCase();
      setState(() => _rows = [for (final r in rows) if (widget.titleOf(r).toLowerCase() != typed) r]);
    } on ApiException {
      // Suggestions are a convenience; typing still works.
    }
  }

  void _pick(Map<String, dynamic> row) {
    _request++;
    widget.controller.text = widget.titleOf(row);
    setState(() => _rows = const []);
    widget.onPicked(row);
  }

  void _close() {
    _debounce?.cancel();
    _request++;
    if (_rows.isNotEmpty) setState(() => _rows = const []);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Focus(
      onFocusChange: (hasFocus) {
        if (!hasFocus) _close();
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppTextField(
            label: widget.label,
            controller: widget.controller,
            mandatory: widget.mandatory,
            highlighted: widget.highlighted,
            capitalization: TextCapitalization.characters,
            onChanged: _typed,
          ),
          if (_rows.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: AppCard(
                child: Column(
                  children: [
                    for (final row in _rows)
                      InkWell(
                        onTap: () => _pick(row),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                          child: Row(
                            children: [
                              const Icon(Icons.history, size: 18, color: Palette.onSurfaceMuted),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(widget.titleOf(row), style: text.labelMedium),
                                    if (widget.subtitleOf(row).isNotEmpty)
                                      Text(
                                        widget.subtitleOf(row),
                                        style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                                      ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
