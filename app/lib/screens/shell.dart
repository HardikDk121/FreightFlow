import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/session.dart';
import '../theme/app_theme.dart';
import 'account/account_screen.dart';
import 'masterdata/master_data_screen.dart';
import 'team/users_screen.dart';

/// The signed-in app: bottom navigation over the top-level screens.
/// The Team tab exists only for admins.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final isAdmin = context.select<Session, bool>((s) => s.user?.isAdmin ?? false);
    final tabs = <(NavigationDestination, Widget)>[
      (
        const NavigationDestination(
          icon: Icon(Icons.inventory_2_outlined),
          selectedIcon: Icon(Icons.inventory_2),
          label: 'Master data',
        ),
        const MasterDataScreen(),
      ),
      if (isAdmin)
        (
          const NavigationDestination(
            icon: Icon(Icons.group_outlined),
            selectedIcon: Icon(Icons.group),
            label: 'Team',
          ),
          const UsersScreen(),
        ),
      (
        const NavigationDestination(
          icon: Icon(Icons.person_outline),
          selectedIcon: Icon(Icons.person),
          label: 'Account',
        ),
        const AccountScreen(),
      ),
    ];
    // An admin demoted while on the last tab would otherwise point past the end.
    final index = _index < tabs.length ? _index : tabs.length - 1;
    return Scaffold(
      body: IndexedStack(index: index, children: [for (final tab in tabs) tab.$2]),
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.outline))),
        child: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: (i) => setState(() => _index = i),
          destinations: [for (final tab in tabs) tab.$1],
        ),
      ),
    );
  }
}
