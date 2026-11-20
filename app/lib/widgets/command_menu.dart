import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

/// One thing the command menu can do: open a screen the person is allowed to use.
class Command {
  const Command(this.icon, this.label, this.open, {this.keywords = ''});

  final IconData icon;
  final String label;
  final VoidCallback open;

  /// Extra words that find it ("money" finds Collections).
  final String keywords;
}

/// The shortcut that opens the menu on a keyboard: Ctrl+K, or Cmd+K on a Mac.
const commandMenuShortcuts = [
  SingleActivator(LogicalKeyboardKey.keyK, control: true),
  SingleActivator(LogicalKeyboardKey.keyK, meta: true),
];

/// Find an LR by number or party, or jump to any screen, from one search box.
/// [openLr] receives the LR row the person picked.
Future<void> showCommandMenu(
  BuildContext context, {
  required List<Command> commands,
  required void Function(Map<String, dynamic> lr) openLr,
}) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _CommandMenu(commands: commands, openLr: openLr),
    );

class _CommandMenu extends StatefulWidget {
  const _CommandMenu({required this.commands, required this.openLr});

  final List<Command> commands;
  final void Function(Map<String, dynamic> lr) openLr;

  @override
  State<_CommandMenu> createState() => _CommandMenuState();
}

class _CommandMenuState extends State<_CommandMenu> {
  final _query = TextEditingController();
  Timer? _debounce;
  List<Map<String, dynamic>> _lrs = const [];
  int _request = 0;

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _changed(String value) {
    setState(() {});
    _debounce?.cancel();
    if (value.trim().length < 2) {
      setState(() => _lrs = const []);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), () async {
      final request = ++_request;
      try {
        final rows = await context.read<ApiClient>().get('/lrs', query: {'q': value.trim(), 'limit': '8'}) as List;
        if (mounted && request == _request) setState(() => _lrs = rows.cast<Map<String, dynamic>>());
      } on ApiException {
        // Searching is a convenience; a failed search just shows no LRs.
      }
    });
  }

  void _run(VoidCallback action) {
    Navigator.of(context).pop();
    action();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final q = _query.text.trim().toLowerCase();
    final commands = [
      for (final c in widget.commands)
        if (q.isEmpty || '${c.label} ${c.keywords}'.toLowerCase().contains(q)) c,
    ];
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.75,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: TextField(
                controller: _query,
                autofocus: true,
                onChanged: _changed,
                textInputAction: TextInputAction.search,
                decoration: const InputDecoration(hintText: 'Find an LR or a party, or go to…', prefixIcon: Icon(Icons.search)),
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                children: [
                  for (final lr in _lrs)
                    ListTile(
                      leading: const Icon(Icons.receipt_long_outlined),
                      title: Text(lr['lr_number'] as String, style: text.titleMedium),
                      subtitle: Text('${lr['consignor_name']} → ${lr['consignee_name']}', style: text.bodySmall),
                      onTap: () => _run(() => widget.openLr(lr)),
                    ),
                  if (_lrs.isNotEmpty) const Divider(),
                  for (final c in commands)
                    ListTile(
                      leading: Icon(c.icon, color: Palette.onSurface),
                      title: Text(c.label),
                      onTap: () => _run(c.open),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
