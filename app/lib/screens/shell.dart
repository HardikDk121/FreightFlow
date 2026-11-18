import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'chat/chat_screen.dart';
import 'home/home_screen.dart';
import 'lr/lr_list_screen.dart';
import 'pending/pending_screen.dart';
import 'trips/trips_screen.dart';

/// The signed-in app: a floating dark navigation bar over the five working screens.
/// Account, team and master data open from the icon on Home.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  static const _tabs = <(IconData, String, Widget)>[
    (Icons.home_outlined, 'Home', HomeScreen()),
    (Icons.receipt_long_outlined, 'LRs', LrListScreen()),
    (Icons.inventory_2_outlined, 'Pending', PendingScreen()),
    (Icons.local_shipping_outlined, 'Trips', TripsScreen()),
    (Icons.chat_bubble_outline, 'Ask', ChatScreen()),
  ];

  int _index = 0;

  /// Tabs are built the first time they are opened, and rebuilt (so they reload) when re-selected.
  final Map<int, int> _visits = {0: 0};

  void _select(int index) => setState(() {
        // The chat keeps its conversation; the other tabs show data that may have changed.
        final keep = _tabs[index].$3 is ChatScreen && _visits.containsKey(index);
        if (!keep) _visits[index] = (_visits[index] ?? -1) + 1;
        _index = index;
      });

  @override
  Widget build(BuildContext context) => Scaffold(
        // Screens scroll underneath the floating bar; each list leaves room for it at the bottom.
        extendBody: true,
        body: ShellScope(
          goTo: _select,
          child: IndexedStack(
            index: _index,
            children: [
              for (var i = 0; i < _tabs.length; i++)
                _visits.containsKey(i)
                    ? KeyedSubtree(key: ValueKey('$i-${_visits[i]}'), child: _tabs[i].$3)
                    : const SizedBox.shrink(),
            ],
          ),
        ),
        bottomNavigationBar: _FloatingNavBar(
          items: [for (final tab in _tabs) (tab.$1, tab.$2)],
          index: _index,
          onSelect: _select,
        ),
      );
}

/// Space to leave under a tab's scrolling content so its last item clears the floating bar.
const navBarClearance = 112.0;

/// Lets a tab send the person to another tab, such as Home's "Pending goods" tile.
class ShellScope extends InheritedWidget {
  const ShellScope({super.key, required this.goTo, required super.child});

  final ValueChanged<int> goTo;

  /// Null outside the shell, for a screen pushed on its own.
  static ShellScope? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<ShellScope>();

  @override
  bool updateShouldNotify(ShellScope oldWidget) => false;
}

/// Tab positions, for [ShellScope.goTo].
abstract final class ShellTab {
  static const lrs = 1;
  static const pending = 2;
  static const trips = 3;
}

class _FloatingNavBar extends StatelessWidget {
  const _FloatingNavBar({required this.items, required this.index, required this.onSelect});

  final List<(IconData, String)> items;
  final int index;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return SafeArea(
      minimum: const EdgeInsets.fromLTRB(14, 0, 14, 10),
      child: Container(
        height: 72,
        padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(
          color: Palette.ink,
          borderRadius: BorderRadius.circular(999),
          boxShadow: const [BoxShadow(color: Color(0x33000000), blurRadius: 18, offset: Offset(0, 6))],
        ),
        child: Row(
          children: [
            for (var i = 0; i < items.length; i++)
              Expanded(
                child: Semantics(
                  selected: i == index,
                  button: true,
                  label: items[i].$2,
                  excludeSemantics: true,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () => onSelect(i),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 220),
                      curve: Curves.easeOut,
                      decoration: BoxDecoration(
                        color: i == index ? Palette.primary : Colors.transparent,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(items[i].$1, size: 22, color: i == index ? Palette.onPrimary : Palette.onInkMuted),
                          const SizedBox(height: 3),
                          Text(
                            items[i].$2,
                            maxLines: 1,
                            style: text.bodySmall!.copyWith(
                              fontWeight: FontWeight.w700,
                              color: i == index ? Palette.onPrimary : Palette.onInkMuted,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
