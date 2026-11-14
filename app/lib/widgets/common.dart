import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

/// White surface with a hairline border and 16dp corners. Flat: no shadow.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Material(
        color: Palette.surface,
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: Palette.outline),
        ),
        child: child,
      );
}

/// Centred icon, title, line of text and one optional button. Used for empty and error states.
class MessageView extends StatelessWidget {
  const MessageView({
    super.key,
    required this.icon,
    required this.title,
    required this.body,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String body;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: StatusColors.of(context).muted),
            const SizedBox(height: 16),
            Text(title, style: text.titleMedium, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(body, style: text.bodyMedium, textAlign: TextAlign.center),
            if (actionLabel != null) ...[
              const SizedBox(height: 24),
              OutlinedButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Grey placeholder rows shown while a list loads.
class SkeletonList extends StatelessWidget {
  const SkeletonList({super.key});

  @override
  Widget build(BuildContext context) => ListView.separated(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        itemCount: 6,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, __) => Container(
          height: 72,
          decoration: BoxDecoration(color: Palette.outline, borderRadius: BorderRadius.circular(16)),
        ),
      );
}

class ErrorBanner extends StatelessWidget {
  const ErrorBanner(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Palette.errorContainer, borderRadius: BorderRadius.circular(12)),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline, color: Palette.error, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                message,
                style: Theme.of(context).textTheme.bodyMedium!.copyWith(color: Palette.error),
              ),
            ),
          ],
        ),
      );
}

/// 28dp pill with a word in it. Colour never carries the meaning alone.
class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, required this.background, required this.foreground});

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) => Container(
        height: 28,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        alignment: Alignment.center,
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(14)),
        child: Text(label, style: Theme.of(context).textTheme.labelMedium!.copyWith(color: foreground)),
      );
}

/// Text field with its label above it.
class AppTextField extends StatelessWidget {
  const AppTextField({
    super.key,
    required this.label,
    required this.controller,
    this.mandatory = false,
    this.minLength,
    this.check,
    this.obscure = false,
    this.keyboardType,
    this.capitalization = TextCapitalization.none,
  });

  final String label;
  final TextEditingController controller;
  final bool mandatory;
  final int? minLength;

  /// Extra validation for a non-empty value. Returns an error message or null.
  final String? Function(String value)? check;
  final bool obscure;
  final TextInputType? keyboardType;
  final TextCapitalization capitalization;

  String? _validate(String? raw) {
    final value = raw?.trim() ?? '';
    if (value.isEmpty) return mandatory ? 'Required' : null;
    if (minLength != null && value.length < minLength!) return 'At least $minLength characters';
    return check?.call(value);
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(mandatory ? label : '$label (optional)', style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 8),
            TextFormField(
              controller: controller,
              obscureText: obscure,
              keyboardType: keyboardType,
              textCapitalization: capitalization,
              style: Theme.of(context).textTheme.bodyLarge,
              validator: _validate,
            ),
          ],
        ),
      );
}

/// A labelled row of pill choices; exactly one is selected.
class ChoiceField<T> extends StatelessWidget {
  const ChoiceField({
    super.key,
    required this.label,
    required this.options,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final Map<T, String> options;
  final T value;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final option in options.entries)
                  ChoiceChip(
                    label: Text(option.value),
                    selected: option.key == value,
                    showCheckmark: false,
                    shape: const StadiumBorder(side: BorderSide(color: Palette.outline)),
                    backgroundColor: Palette.surface,
                    selectedColor: Palette.primaryContainer,
                    onSelected: (_) => onChanged(option.key),
                  ),
              ],
            ),
          ],
        ),
      );
}

/// A labelled on/off switch in a card.
class SwitchField extends StatelessWidget {
  const SwitchField({super.key, required this.label, required this.value, required this.onChanged});

  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: AppCard(
          child: SwitchListTile(
            title: Text(label, style: Theme.of(context).textTheme.bodyLarge),
            value: value,
            onChanged: onChanged,
          ),
        ),
      );
}

/// Form state shared by every screen that submits to the API: validates, shows a
/// busy button while the call runs, and shows the server's message if it fails.
mixin Submitter<T extends StatefulWidget> on State<T> {
  final formKey = GlobalKey<FormState>();
  bool busy = false;
  String? error;

  Future<void> submit(Future<void> Function() action) async {
    if (!formKey.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }
}

/// Scaffold for a [Submitter] screen: app bar, fields, error banner, one primary button.
class FormPage extends StatelessWidget {
  const FormPage({
    super.key,
    required this.title,
    required this.formKey,
    required this.children,
    required this.submitLabel,
    required this.onSubmit,
    required this.busy,
    required this.error,
  });

  final String title;
  final GlobalKey<FormState> formKey;
  final List<Widget> children;
  final String submitLabel;
  final VoidCallback onSubmit;
  final bool busy;
  final String? error;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: SafeArea(
          child: Form(
            key: formKey,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 16)],
                ...children,
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: busy ? null : onSubmit,
                  child: busy
                      ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(submitLabel),
                ),
              ],
            ),
          ),
        ),
      );
}
