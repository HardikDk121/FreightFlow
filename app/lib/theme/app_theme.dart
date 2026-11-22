import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/cupertino.dart';
/// Colour tokens from DESIGN.md.
///
/// Two surfaces carry the brand: [ink], a near-black used for hero bands, the navigation bar and
/// selected states; and [primary], an amber used only as a fill behind dark text (buttons, the
/// active tab, progress). Amber is never used for text or thin icons on white: it is too light
/// to read there.
abstract final class Palette {
  static const background = Color(0xFFF5F5F7);
  static const surface = Color(0xFFFFFFFF);
  static const onSurface = Color(0xFF14141A);
  static const onSurfaceVariant = Color(0xFF4A4A55);
  static const onSurfaceMuted = Color(0xFF6B6B76);
  static const outline = Color(0xFFE4E4EA);
  static const scrim = Color(0x8A000000);

  static const ink = Color(0xFF14141A);
  static const inkRaised = Color(0xFF24242D);
  static const onInk = Color(0xFFFFFFFF);
  static const onInkMuted = Color(0xFFB4B4BF);

  static const primary = Color(0xFFF5B82E);
  static const primaryPressed = Color(0xFFE3A511);
  static const onPrimary = Color(0xFF14141A);
  static const primaryContainer = Color(0xFFFFF1CF);
  static const onPrimaryContainer = Color(0xFF6B4A00);

  /// Text links and text buttons: ink, so they read on white and on the grey page.
  static const link = ink;

  static const error = Color(0xFFB42318);
  static const errorContainer = Color(0xFFFDE6E1);
  static const danger = Color(0xFFC4320A);
  static const warning = Color(0xFF8F4300);
  static const warningContainer = Color(0xFFFFE9D4);
  static const success = Color(0xFF1E7A3A);
  static const successContainer = Color(0xFFE2F5E6);
  static const disabled = Color(0xFFE6E6EB);
  static const onDisabled = Color(0xFF9A9AA4);
}

/// Tokens Material's ColorScheme has no slot for.
@immutable
class StatusColors extends ThemeExtension<StatusColors> {
  const StatusColors({required this.muted, required this.success, required this.successContainer});

  final Color muted;
  final Color success;
  final Color successContainer;

  static StatusColors of(BuildContext context) => Theme.of(context).extension<StatusColors>()!;

  @override
  StatusColors copyWith({Color? muted, Color? success, Color? successContainer}) => StatusColors(
        muted: muted ?? this.muted,
        success: success ?? this.success,
        successContainer: successContainer ?? this.successContainer,
      );

  @override
  StatusColors lerp(ThemeExtension<StatusColors>? other, double t) {
    if (other is! StatusColors) return this;
    return StatusColors(
      muted: Color.lerp(muted, other.muted, t)!,
      success: Color.lerp(success, other.success, t)!,
      successContainer: Color.lerp(successContainer, other.successContainer, t)!,
    );
  }
}

final ThemeData appTheme = _buildTheme();

/// Body text on dark surfaces (hero bands, dark cards).
TextStyle onInk(TextStyle style, {bool muted = false}) =>
    style.copyWith(color: muted ? Palette.onInkMuted : Palette.onInk);

ThemeData _buildTheme() {
  const scheme = ColorScheme.light(
    primary: Palette.primary,
    onPrimary: Palette.onPrimary,
    primaryContainer: Palette.primaryContainer,
    onPrimaryContainer: Palette.onPrimaryContainer,
    secondary: Palette.ink,
    onSecondary: Palette.onInk,
    secondaryContainer: Palette.primaryContainer,
    onSecondaryContainer: Palette.onPrimaryContainer,
    error: Palette.error,
    onError: Palette.onInk,
    errorContainer: Palette.errorContainer,
    onErrorContainer: Palette.error,
    surface: Palette.surface,
    onSurface: Palette.onSurface,
    onSurfaceVariant: Palette.onSurfaceVariant,
    outline: Palette.outline,
    outlineVariant: Palette.outline,
    scrim: Palette.scrim,
  );

  // Plus Jakarta Sans has no Devanagari or Gujarati glyphs; these cover Hindi and Gujarati text.
  final fallback = [
    GoogleFonts.notoSansDevanagari().fontFamily!,
    GoogleFonts.notoSansGujarati().fontFamily!,
  ];
  TextStyle style(double size, FontWeight weight, double height, {double spacing = 0}) =>
      GoogleFonts.plusJakartaSans(
        fontSize: size,
        fontWeight: weight,
        height: height,
        letterSpacing: spacing,
        color: Palette.onSurface,
        // Every digit the same width, so amounts and quantities line up in columns and do not jump.
        fontFeatures: const [FontFeature.tabularFigures()],
      ).copyWith(fontFamilyFallback: fallback);

  final text = TextTheme(
    displaySmall: style(32, FontWeight.w800, 1.15, spacing: -0.6), // hero headlines
    headlineMedium: style(26, FontWeight.w800, 1.2, spacing: -0.4), // big numbers, greetings
    titleLarge: style(22, FontWeight.w800, 1.25, spacing: -0.3), // screen titles
    titleMedium: style(16, FontWeight.w700, 1.35),
    bodyLarge: style(16, FontWeight.w500, 1.45),
    bodyMedium: style(14, FontWeight.w500, 1.45),
    labelLarge: style(15, FontWeight.w700, 1.25),
    labelMedium: style(13, FontWeight.w600, 1.3),
    labelSmall: style(11, FontWeight.w700, 1.3, spacing: 0.8), // eyebrow labels, upper-cased
    bodySmall: style(12, FontWeight.w500, 1.35),
  );

  OutlineInputBorder fieldBorder(Color color, [double width = 1]) => OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: color, width: width),
      );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Palette.background,
    // Android shows the previous screen as you swipe back (needs enableOnBackInvokedCallback in the manifest).
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: PredictiveBackPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      },
    ),
    textTheme: text,
    splashFactory: InkSparkle.splashFactory,
    extensions: const [
      StatusColors(
        muted: Palette.onSurfaceMuted,
        success: Palette.success,
        successContainer: Palette.successContainer,
      ),
    ],
    appBarTheme: AppBarTheme(
      backgroundColor: Palette.background,
      foregroundColor: Palette.onSurface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      toolbarHeight: 64,
      titleSpacing: 8,
      titleTextStyle: text.titleLarge,
    ),
    dividerTheme: const DividerThemeData(color: Palette.outline, thickness: 1, space: 1),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: Palette.primary,
        foregroundColor: Palette.onPrimary,
        disabledBackgroundColor: Palette.disabled,
        disabledForegroundColor: Palette.onDisabled,
        minimumSize: const Size.fromHeight(54),
        shape: const StadiumBorder(),
        textStyle: text.labelLarge,
        elevation: 0,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(50),
        foregroundColor: Palette.ink,
        side: const BorderSide(color: Palette.ink, width: 1.2),
        shape: const StadiumBorder(),
        textStyle: text.labelLarge,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(48, 48),
        foregroundColor: Palette.link,
        textStyle: text.labelLarge,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: Palette.onSurface, minimumSize: const Size(48, 48)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Palette.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      hintStyle: text.bodyLarge!.copyWith(color: Palette.onSurfaceMuted),
      suffixStyle: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
      border: fieldBorder(Palette.outline),
      enabledBorder: fieldBorder(Palette.outline),
      focusedBorder: fieldBorder(Palette.primary, 1.8),
      errorBorder: fieldBorder(Palette.error),
      focusedErrorBorder: fieldBorder(Palette.error, 1.8),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: Palette.surface,
      selectedColor: Palette.ink,
      labelStyle: text.labelMedium,
      secondaryLabelStyle: text.labelMedium!.copyWith(color: Palette.onInk),
      side: const BorderSide(color: Palette.outline),
      shape: const StadiumBorder(),
      showCheckmark: false,
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.all(Palette.surface),
      trackColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? Palette.primary : Palette.disabled,
      ),
      trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? Palette.primary : Colors.transparent,
      ),
      checkColor: WidgetStateProperty.all(Palette.onPrimary),
      side: const BorderSide(color: Palette.onSurfaceMuted, width: 1.5),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: Palette.ink),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: Palette.ink,
      contentTextStyle: text.bodyMedium!.copyWith(color: Palette.onInk),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Palette.surface,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
    datePickerTheme: DatePickerThemeData(
      backgroundColor: Palette.surface,
      surfaceTintColor: Colors.transparent,
      headerBackgroundColor: Palette.ink,
      headerForegroundColor: Palette.onInk,
      rangeSelectionBackgroundColor: Palette.primaryContainer,
      rangePickerBackgroundColor: Palette.surface,
      rangePickerHeaderBackgroundColor: Palette.ink,
      rangePickerHeaderForegroundColor: Palette.onInk,
      todayBorder: const BorderSide(color: Palette.primary, width: 1.5),
      dayBackgroundColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? Palette.ink : null,
      ),
      dayForegroundColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? Palette.onInk : null,
      ),
      confirmButtonStyle: TextButton.styleFrom(foregroundColor: Palette.ink),
      cancelButtonStyle: TextButton.styleFrom(foregroundColor: Palette.onSurfaceVariant),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: Palette.primary,
      foregroundColor: Palette.onPrimary,
      elevation: 2,
      focusElevation: 2,
      hoverElevation: 2,
      highlightElevation: 2,
      shape: StadiumBorder(),
    ),
  );
}
