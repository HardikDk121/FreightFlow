import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

/// White rounded surface on the grey page. Flat: depth comes from the white-on-grey step.
/// [color] switches it to a tinted or dark card; [onTap] makes the whole card tappable.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.color = Palette.surface, this.onTap, this.padding});

  final Widget child;
  final Color color;
  final VoidCallback? onTap;

  /// Inner padding; null leaves the child to pad itself (for ListTiles and similar).
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final content = padding == null ? child : Padding(padding: padding!, child: child);
    return Material(
      color: color,
      clipBehavior: Clip.antiAlias,
      borderRadius: BorderRadius.circular(22),
      child: onTap == null ? content : InkWell(onTap: onTap, child: content),
    );
  }
}

/// A dark card: the visual weight for one key fact per screen (an LR's headline, a load's capacity).
class DarkPanel extends StatelessWidget {
  const DarkPanel({super.key, required this.child, this.padding = const EdgeInsets.all(20)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) => AppCard(color: Palette.ink, padding: padding, child: child);
}

/// Tones for small status pills. Each pairs a pale fill with a dark text colour that reads on it.
enum Tone {
  neutral(Palette.surface, Palette.onSurface),
  info(Palette.primaryContainer, Palette.onPrimaryContainer),
  success(Palette.successContainer, Palette.success),
  warning(Palette.warningContainer, Palette.warning),
  danger(Palette.errorContainer, Palette.error),
  dark(Palette.ink, Palette.onInk);

  const Tone(this.background, this.foreground);

  final Color background;
  final Color foreground;
}

/// Pill with a word in it, sized to its text. Colour never carries the meaning alone.
class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, required this.background, required this.foreground});

  StatusChip.tone(this.label, Tone tone, {super.key})
      : background = tone.background,
        foreground = tone.foreground;

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(999)),
        child: Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelMedium!.copyWith(color: foreground),
        ),
      );
}

/// Small upper-case label above a group, like "MANAGE" or "GODOWN OVERVIEW".
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.onDark = false});

  final String text;
  final bool onDark;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 10),
        child: Text(
          text.toUpperCase(),
          style: Theme.of(context).textTheme.labelSmall!.copyWith(
                color: onDark ? Palette.onInkMuted : Palette.onSurfaceMuted,
              ),
        ),
      );
}

/// Section title with a small icon, used to break long forms and screens into parts.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, required this.icon, this.trailing});

  final String title;
  final IconData icon;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 12),
        child: Row(
          children: [
            Icon(icon, size: 20, color: Palette.onSurface),
            const SizedBox(width: 10),
            Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium!.copyWith(fontSize: 18))),
            if (trailing != null) trailing!,
          ],
        ),
      );
}

/// One line under a screen's title saying what the screen is for.
class PageIntro extends StatelessWidget {
  const PageIntro(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Text(text, style: Theme.of(context).textTheme.bodyMedium!.copyWith(color: Palette.onSurfaceMuted)),
      );
}

/// The dark band at the top of the main screens: an optional eyebrow, a big title, a line under it,
/// and an optional [child] (such as a route card) that sits inside the band.
class HeroHeader extends StatelessWidget {
  const HeroHeader({
    super.key,
    required this.title,
    this.eyebrow,
    this.subtitle,
    this.leading,
    this.trailing,
    this.child,
    this.showBack = false,
  });

  final String title;
  final String? eyebrow;
  final String? subtitle;

  /// Shown above the title, such as the app's wordmark.
  final Widget? leading;
  final Widget? trailing;
  final Widget? child;
  final bool showBack;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Container(
      width: double.infinity,
      color: Palette.ink,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 22),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (showBack || leading != null || trailing != null)
                SizedBox(
                  height: 48,
                  child: Row(
                    children: [
                      if (showBack)
                        IconButton(
                          tooltip: 'Back',
                          padding: EdgeInsets.zero,
                          alignment: Alignment.centerLeft,
                          icon: const Icon(Icons.arrow_back, color: Palette.onInk),
                          onPressed: () => Navigator.of(context).maybePop(),
                        ),
                      if (leading != null) leading!,
                      const Spacer(),
                      if (trailing != null) trailing!,
                    ],
                  ),
                ),
              if (eyebrow != null) SectionLabel(eyebrow!, onDark: true),
              if (title.isNotEmpty) Text(title, style: onInk(text.displaySmall!)),
              if (subtitle != null) ...[
                const SizedBox(height: 6),
                Text(subtitle!, style: onInk(text.bodyMedium!, muted: true)),
              ],
              if (child != null) ...[const SizedBox(height: 18), child!],
            ],
          ),
        ),
      ),
    );
  }
}

/// The FreightFlow wordmark: amber on dark, used on hero bands.
class Wordmark extends StatelessWidget {
  const Wordmark({super.key});

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: const BoxDecoration(color: Palette.primary, shape: BoxShape.circle),
            child: const Icon(Icons.north_east, size: 18, color: Palette.onPrimary),
          ),
          const SizedBox(width: 10),
          Text('FreightFlow', style: onInk(Theme.of(context).textTheme.titleLarge!)),
        ],
      );
}

/// A row of options where exactly one is chosen: a grey track with the chosen option in dark.
class Segmented<T> extends StatelessWidget {
  const Segmented({super.key, required this.options, required this.value, required this.onChanged});

  final Map<T, String> options;
  final T value;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: Palette.disabled, borderRadius: BorderRadius.circular(999)),
      child: Row(
        children: [
          for (final option in options.entries)
            Expanded(
              child: Semantics(
                selected: option.key == value,
                button: true,
                child: GestureDetector(
                  onTap: () => onChanged(option.key),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    curve: Curves.easeOut,
                    height: 42,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: option.key == value ? Palette.ink : Colors.transparent,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      option.value,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: text.labelMedium!.copyWith(
                        color: option.key == value ? Palette.onInk : Palette.onSurfaceVariant,
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

/// A big number with a label under it.
class MetricTile extends StatelessWidget {
  const MetricTile({super.key, required this.value, required this.label, this.onDark = false});

  final String value;
  final String label;
  final bool onDark;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(value, style: text.headlineMedium!.copyWith(color: onDark ? Palette.onInk : Palette.onSurface)),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: text.bodySmall!.copyWith(color: onDark ? Palette.onInkMuted : Palette.onSurfaceMuted),
        ),
      ],
    );
  }
}

/// A labelled amber bar on a dark card: how full something is. Turns red past 100%.
class MeterBar extends StatelessWidget {
  const MeterBar({super.key, required this.label, required this.detail, required this.percent});

  final String label;
  final String detail;
  final int percent;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final over = percent > 100;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(label, style: onInk(text.labelLarge!))),
              Text('$percent%', style: onInk(text.labelLarge!).copyWith(color: over ? const Color(0xFFFF8A75) : null)),
            ],
          ),
          const SizedBox(height: 4),
          Text(detail, style: onInk(text.bodySmall!, muted: true)),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: (percent / 100).clamp(0, 1).toDouble(),
              minHeight: 8,
              backgroundColor: Palette.inkRaised,
              color: over ? const Color(0xFFFF8A75) : Palette.primary,
            ),
          ),
        ],
      ),
    );
  }
}

/// Empty and error states: an icon in a soft circle, a title, a line, and one optional button.
/// [card] puts it on a white card, for use inside a list rather than filling the screen.
class MessageView extends StatelessWidget {
  const MessageView({
    super.key,
    required this.icon,
    required this.title,
    required this.body,
    this.actionLabel,
    this.onAction,
    this.card = false,
    this.tone = Tone.neutral,
  });

  final IconData icon;
  final String title;
  final String body;
  final String? actionLabel;
  final VoidCallback? onAction;
  final bool card;

  /// The circle's colours. Success for "all clear", danger for errors.
  final Tone tone;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final circle = tone == Tone.neutral ? Palette.background : tone.background;
    final content = Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 84,
          height: 84,
          decoration: BoxDecoration(color: circle, shape: BoxShape.circle),
          child: Icon(icon, size: 40, color: tone == Tone.neutral ? Palette.onSurface : tone.foreground),
        ),
        const SizedBox(height: 20),
        Text(title, style: text.titleLarge, textAlign: TextAlign.center),
        const SizedBox(height: 8),
        Text(body, style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted), textAlign: TextAlign.center),
        if (actionLabel != null) ...[
          const SizedBox(height: 24),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Palette.ink,
              foregroundColor: Palette.onInk,
              minimumSize: const Size(0, 48),
              padding: const EdgeInsets.symmetric(horizontal: 28),
            ),
            onPressed: onAction,
            child: Text(actionLabel!),
          ),
        ],
      ],
    );
    if (card) {
      return AppCard(padding: const EdgeInsets.fromLTRB(24, 32, 24, 32), child: Center(child: content));
    }
    return Center(child: SingleChildScrollView(padding: const EdgeInsets.all(32), child: content));
  }
}

/// Grey placeholder rows shown while a list loads.
class SkeletonList extends StatelessWidget {
  const SkeletonList({super.key});

  @override
  Widget build(BuildContext context) => ListView.separated(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(20),
        itemCount: 5,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, __) => Container(
          height: 96,
          decoration: BoxDecoration(color: Palette.disabled, borderRadius: BorderRadius.circular(22)),
        ),
      );
}

class ErrorBanner extends StatelessWidget {
  const ErrorBanner(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: Palette.errorContainer, borderRadius: BorderRadius.circular(16)),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline, color: Palette.error, size: 20),
            const SizedBox(width: 10),
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
    this.hint,
    this.autofillHints,
    this.lines = 1,
  });

  final String label;
  final TextEditingController controller;
  final bool mandatory;

  /// Shown at the right edge of the field: "kg", "Rs".
  final String? unit;

  /// A neutral line under the field, such as how a calculated value was worked out.
  final String? helper;

  /// Placeholder shown while the field is empty, such as "e.g. GJ03CW0620".
  final String? hint;

  /// What the phone's password manager or keyboard may offer here (AutofillHints.email, ...).
  final List<String>? autofillHints;

  /// Height in text lines; more than one makes a multi-line box.
  final int lines;

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
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text.rich(
            TextSpan(
              text: label,
              children: [
                if (!mandatory)
                  TextSpan(text: ' · optional', style: text.labelMedium!.copyWith(color: Palette.onSurfaceMuted)),
              ],
            ),
            style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant),
          ),
          const SizedBox(height: 8),
          TextFormField(
            controller: controller,
            obscureText: obscure,
            keyboardType: lines > 1 ? TextInputType.multiline : keyboardType,
            minLines: lines,
            maxLines: lines,
            autofillHints: autofillHints,
            textCapitalization: capitalization,
            style: text.bodyLarge,
            validator: _validate,
            autovalidateMode: AutovalidateMode.onUserInteraction,
            onChanged: onChanged,
            decoration: (highlighted ? _highlightDecoration(context) : const InputDecoration()).copyWith(
              hintText: hint,
              suffixText: unit,
              helperText: highlighted ? null : helper,
              helperStyle: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
              helperMaxLines: 2,
              errorMaxLines: 2,
            ),
          ),
        ],
      ),
    );
  }
}

InputDecoration _highlightDecoration(BuildContext context) {
  final border = OutlineInputBorder(
    borderRadius: BorderRadius.circular(14),
    borderSide: const BorderSide(color: Palette.primary, width: 1.4),
  );
  return InputDecoration(
    fillColor: Palette.primaryContainer,
    enabledBorder: border,
    suffixIcon: const Icon(Icons.auto_awesome, color: Palette.onPrimaryContainer, size: 20),
    helperText: 'Filled in for you. Check it.',
    helperStyle: Theme.of(context).textTheme.bodySmall!.copyWith(color: Palette.onPrimaryContainer),
  );
}

/// A field that opens a picker (a date, a state, a package type) instead of taking typing.
/// Looks like [AppTextField] so a form reads as one set of fields.
class PickerField extends StatelessWidget {
  const PickerField({
    super.key,
    required this.label,
    required this.value,
    required this.placeholder,
    required this.onTap,
    this.icon = Icons.expand_more,
    this.mandatory = true,
    this.note,
    this.noteTone = Tone.neutral,
  });

  final String label;

  /// What is chosen; null shows [placeholder].
  final String? value;
  final String placeholder;
  final VoidCallback onTap;
  final IconData icon;
  final bool mandatory;

  /// A line under the field, such as "This date has passed" or "From the GST number. Check it."
  final String? note;
  final Tone noteTone;

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
              text: label,
              children: [
                if (!mandatory)
                  TextSpan(text: ' · optional', style: text.labelMedium!.copyWith(color: Palette.onSurfaceMuted)),
              ],
            ),
            style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant),
          ),
          const SizedBox(height: 8),
          Material(
            color: Palette.surface,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
              side: const BorderSide(color: Palette.outline),
            ),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        value ?? placeholder,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: text.bodyLarge!.copyWith(color: value == null ? Palette.onSurfaceMuted : null),
                      ),
                    ),
                    Icon(icon, size: 20, color: Palette.onSurfaceVariant),
                  ],
                ),
              ),
            ),
          ),
          if (note != null) ...[
            const SizedBox(height: 6),
            Text(
              note!,
              style: text.bodySmall!.copyWith(
                color: noteTone == Tone.neutral ? Palette.onSurfaceMuted : noteTone.foreground,
              ),
            ),
          ],
        ],
      ),
    );
  }
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
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: text.labelMedium!.copyWith(color: Palette.onSurfaceVariant)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final option in options.entries)
                ChoiceChip(
                  label: Text(option.value),
                  labelStyle: text.labelMedium!.copyWith(
                    color: option.key == value ? Palette.onInk : Palette.onSurface,
                  ),
                  selected: option.key == value,
                  showCheckmark: false,
                  side: BorderSide(color: option.key == value ? Palette.ink : Palette.outline),
                  shape: const StadiumBorder(),
                  backgroundColor: Palette.surface,
                  selectedColor: Palette.ink,
                  onSelected: (_) => onChanged(option.key),
                ),
            ],
          ),
          if (highlighted) ...[
            const SizedBox(height: 6),
            Text(
              'Filled in for you. Check it.',
              style: text.bodySmall!.copyWith(color: Palette.onPrimaryContainer),
            ),
          ],
        ],
      ),
    );
  }
}

/// A labelled on/off switch in a card, with an optional line explaining it.
class SwitchField extends StatelessWidget {
  const SwitchField({super.key, required this.label, required this.value, required this.onChanged, this.subtitle});

  final String label;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: AppCard(
        child: SwitchListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 4),
          title: Text(label, style: text.titleMedium),
          subtitle: subtitle == null
              ? null
              : Text(subtitle!, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
          value: value,
          onChanged: onChanged,
        ),
      ),
    );
  }
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

/// The bottom of a screen, holding its main action. Sits on the page colour, not in a bar.
class BottomBar extends StatelessWidget {
  const BottomBar({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Material(
        color: Palette.background,
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 10, 20, 14),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: children,
            ),
          ),
        ),
      );
}

/// A full-width primary button that shows a spinner while [busy].
class BusyButton extends StatelessWidget {
  const BusyButton({super.key, required this.label, required this.onPressed, this.busy = false, this.icon});

  final String label;
  final VoidCallback? onPressed;
  final bool busy;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => FilledButton(
        onPressed: busy ? null : onPressed,
        child: busy
            ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (icon != null) ...[Icon(icon, size: 20), const SizedBox(width: 8)],
                  Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
                ],
              ),
      );
}

/// Scaffold for a [Submitter] screen: a title with a line saying what it is for, scrolling fields,
/// and a pinned area holding the error (if any), an optional [footer] such as a running total,
/// an optional secondary action, and the one primary button.
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
    this.subtitle,
    this.footer,
    this.secondaryLabel,
    this.onSecondary,
    this.hero,
  });

  /// A dark header that replaces the plain title bar and scrolls away with the fields.
  final Widget? hero;

  final String title;
  final String? subtitle;
  final GlobalKey<FormState> formKey;
  final List<Widget> children;
  final String submitLabel;

  /// Null disables the button, for when the form says what is missing in its [footer].
  final VoidCallback? onSubmit;
  final bool busy;
  final String? error;
  final Widget? footer;

  /// A second, outlined button beside the primary one, such as "Draft PDF".
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  @override
  Widget build(BuildContext context) {
    final primary = BusyButton(label: submitLabel, onPressed: onSubmit, busy: busy);
    final fields = [if (subtitle != null) PageIntro(subtitle!), ...children];
    return Scaffold(
      appBar: hero == null ? AppBar(title: Text(title)) : null,
      body: Form(
        key: formKey,
        child: hero == null
            ? ListView(padding: const EdgeInsets.fromLTRB(20, 0, 20, 24), children: fields)
            : ListView(
                padding: const EdgeInsets.only(bottom: 24),
                children: [
                  hero!,
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: fields),
                  ),
                ],
              ),
      ),
      bottomNavigationBar: BottomBar(
        children: [
          if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 12)],
          if (footer != null) ...[footer!, const SizedBox(height: 12)],
          if (secondaryLabel == null)
            primary
          else
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(minimumSize: const Size(0, 54)),
                    onPressed: busy ? null : onSecondary,
                    child: Text(secondaryLabel!, overflow: TextOverflow.ellipsis),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(child: primary),
              ],
            ),
        ],
      ),
    );
  }
}
