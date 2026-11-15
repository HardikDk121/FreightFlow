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

/// Pill with a word in it, sized to its text. Colour never carries the meaning alone.
class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, required this.background, required this.foreground});

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(999)),
        child: Text(
          label,
          maxLines: 1,
          style: Theme.of(context).textTheme.labelMedium!.copyWith(color: foreground),
        ),
      );
}

/// Section title with a small tinted icon, used to break long forms and screens into parts.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, required this.icon});

  final String title;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 12, bottom: 12),
        child: Row(
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(color: Palette.primaryContainer, borderRadius: BorderRadius.circular(10)),
              child: Icon(icon, size: 18, color: Palette.onPrimaryContainer),
            ),
            const SizedBox(width: 12),
            Text(title, style: Theme.of(context).textTheme.titleMedium),
          ],
        ),
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
    this.highlighted = false,
    this.onChanged,
    this.unit,
    this.helper,
  });

  final String label;
  final TextEditingController controller;
  final bool mandatory;

  /// Shown at the right edge of the field: "kg", "Rs".
  final String? unit;

  /// A neutral line under the field, such as how a calculated value was worked out.
  final String? helper;

  /// Filled in by the app rather than typed: shown in amber until the person edits it.
  final bool highlighted;
  final ValueChanged<String>? onChanged;
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
              autovalidateMode: AutovalidateMode.onUserInteraction,
              onChanged: onChanged,
              decoration: (highlighted ? _highlightDecoration(context) : const InputDecoration()).copyWith(
                suffixText: unit,
                helperText: highlighted ? null : helper,
                helperMaxLines: 2,
                errorMaxLines: 2,
              ),
            ),
          ],
        ),
      );
}

InputDecoration _highlightDecoration(BuildContext context) {
  final border = OutlineInputBorder(
    borderRadius: BorderRadius.circular(12),
    borderSide: const BorderSide(color: Palette.warning),
  );
  return InputDecoration(
    fillColor: Palette.warningContainer,
    enabledBorder: border,
    suffixIcon: const Icon(Icons.warning_amber_rounded, color: Palette.warning),
    helperText: 'Filled in for you. Check it.',
    helperStyle: Theme.of(context).textTheme.bodySmall!.copyWith(color: Palette.warning),
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
    this.highlighted = false,
  });

  final String label;
  final Map<T, String> options;
  final T value;
  final ValueChanged<T> onChanged;

  /// Chosen by the app rather than the person: says so until the person picks.
  final bool highlighted;

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
                    labelStyle: Theme.of(context).textTheme.labelMedium!.copyWith(
                          color: option.key == value ? Palette.onPrimaryContainer : Palette.onSurface,
                        ),
                    selected: option.key == value,
                    showCheckmark: false,
                    side: BorderSide(color: option.key == value ? Palette.primary : Palette.outline),
                    shape: const StadiumBorder(),
                    backgroundColor: Palette.surface,
                    selectedColor: Palette.primaryContainer,
                    onSelected: (_) => onChanged(option.key),
                  ),
              ],
            ),
            if (highlighted) ...[
              const SizedBox(height: 4),
              Text(
                'Filled in for you. Check it.',
                style: Theme.of(context).textTheme.bodySmall!.copyWith(color: Palette.warning),
              ),
            ],
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
    if (!formKey.currentState!.validate()) {
      setState(() => error = 'Some fields need fixing. Look for the red messages.');
      return;
    }
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

/// White bar pinned to the bottom of a screen, for its main action.
class BottomBar extends StatelessWidget {
  const BottomBar({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Material(
        color: Palette.surface,
        child: DecoratedBox(
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.outline))),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: children,
              ),
            ),
          ),
        ),
      );
}

/// Scaffold for a [Submitter] screen: app bar, scrolling fields, and a pinned bar holding the
/// error (if any), an optional [footer] such as a running total, and the one primary button.
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
    this.footer,
  });

  final String title;
  final GlobalKey<FormState> formKey;
  final List<Widget> children;
  final String submitLabel;
  final VoidCallback onSubmit;
  final bool busy;
  final String? error;
  final Widget? footer;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: Form(
          key: formKey,
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 24), children: children),
        ),
        bottomNavigationBar: BottomBar(
          children: [
            if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 12)],
            if (footer != null) ...[footer!, const SizedBox(height: 12)],
            FilledButton(
              onPressed: busy ? null : onSubmit,
              child: busy
                  ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(submitLabel),
            ),
          ],
        ),
      );
}
