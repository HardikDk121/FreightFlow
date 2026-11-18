import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/common.dart';

/// The sign-in family of screens: a dark band with the wordmark, a big title and a line, and the
/// screen's content starting on a white card that overlaps the band's lower edge.
class AuthScaffold extends StatelessWidget {
  const AuthScaffold({super.key, required this.title, required this.subtitle, required this.children});

  final String title;
  final String subtitle;

  /// The first child should be the main white card; the rest follow on the grey page.
  final List<Widget> children;

  static const _bandHeight = 250.0;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final canPop = Navigator.of(context).canPop();
    return Scaffold(
      body: Stack(
        children: [
          Container(height: _bandHeight + MediaQuery.paddingOf(context).top, color: Palette.ink),
          SafeArea(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
              children: [
                SizedBox(
                  height: 48,
                  child: Row(
                    children: [
                      if (canPop)
                        IconButton(
                          tooltip: 'Back',
                          padding: EdgeInsets.zero,
                          alignment: Alignment.centerLeft,
                          icon: const Icon(Icons.arrow_back, color: Palette.onInk),
                          onPressed: () => Navigator.of(context).maybePop(),
                        ),
                      Text('FreightFlow', style: text.titleLarge!.copyWith(color: Palette.primary)),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                Text(title, style: onInk(text.displaySmall!)),
                const SizedBox(height: 6),
                Text(subtitle, style: onInk(text.bodyMedium!, muted: true)),
                const SizedBox(height: 28),
                ...children,
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// A dark note card on the grey page, for reassurance or a secondary path.
class AuthNote extends StatelessWidget {
  const AuthNote({super.key, required this.title, required this.body, this.action, this.onAction});

  final String title;
  final String body;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: AppCard(
        color: Palette.inkRaised,
        onTap: onAction,
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: onInk(text.titleMedium!)),
            const SizedBox(height: 4),
            Text(body, style: onInk(text.bodySmall!, muted: true)),
            if (action != null) ...[
              const SizedBox(height: 8),
              Text(action!, style: text.labelLarge!.copyWith(color: Palette.primary)),
            ],
          ],
        ),
      ),
    );
  }
}

/// A pale confirmation card, shown after a recovery request is sent.
class AuthSent extends StatelessWidget {
  const AuthSent({super.key, required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: AppCard(
        color: Palette.successContainer,
        padding: const EdgeInsets.all(18),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.mark_email_read_outlined, color: Palette.success),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: text.titleMedium!.copyWith(color: Palette.success)),
                  const SizedBox(height: 4),
                  Text(body, style: text.bodySmall!.copyWith(color: Palette.success)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A secondary line with a bold link under it, such as "New to FreightFlow? / Register".
class AuthLink extends StatelessWidget {
  const AuthLink({super.key, required this.lead, required this.action, required this.onTap});

  final String lead;
  final String action;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(lead, style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted)),
          TextButton(
            style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
            onPressed: onTap,
            child: Text(action),
          ),
        ],
      ),
    );
  }
}
