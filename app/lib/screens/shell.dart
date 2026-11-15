import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'chat/chat_screen.dart';
import 'home/home_screen.dart';
import 'lr/lr_list_screen.dart';
import 'pending/pending_screen.dart';
import 'trips/trips_screen.dart';

/// The signed-in app: bottom navigation over the five working screens.
/// Account, team and master data open from the icon on Home.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  static const _tabs = <(IconData, IconData, String, Widget)>[
    (Icons.home_outlined, Icons.home, 'Home', HomeScreen()),
    (Icons.receipt_long_outlined, Icons.receipt_long, 'LRs', LrListScreen()),
    (Icons.inventory_2_outlined, Icons.inventory_2, 'Pending', PendingScreen()),
    (Icons.local_shipping_outlined, Icons.local_shipping, 'Trips', TripsScreen()),
    (Icons.chat_bubble_outline, Icons.chat_bubble, 'Ask', ChatScreen()),
  ];

  int _index = 0;

  /// Tabs are built the first time they are opened, and rebuilt (so they reload) when re-selected.
  final Map<int, int> _visits = {0: 0};

  void _select(int index) => setState(() {
        // The chat keeps its conversation; the other tabs show data that may have changed.
        final keep = _tabs[index].$4 is ChatScreen && _visits.containsKey(index);
        if (!keep) _visits[index] = (_visits[index] ?? -1) + 1;
        _index = index;
      });

  @override
  Widget build(BuildContext context) => Scaffold(
        body: IndexedStack(
          index: _index,
          children: [
            for (var i = 0; i < _tabs.length; i++)
              _visits.containsKey(i)
                  ? KeyedSubtree(key: ValueKey('$i-${_visits[i]}'), child: _tabs[i].$4)
                  : const SizedBox.shrink(),
          ],
        ),
        bottomNavigationBar: DecoratedBox(
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.outline))),
          child: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: _select,
            destinations: [
              for (final tab in _tabs)
                NavigationDestination(icon: Icon(tab.$1), selectedIcon: Icon(tab.$2), label: tab.$3),
            ],
          ),
        ),
      );
}
