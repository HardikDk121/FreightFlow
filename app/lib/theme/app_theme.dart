import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Colour tokens from DESIGN.md.
abstract final class Palette {
  static const background = Color(0xFFF5F5F7);
  static const surface = Color(0xFFFFFFFF);
  static const onSurface = Color(0xFF1D1D1F);
  static const onSurfaceVariant = Color(0xFF444445);
  static const onSurfaceMuted = Color(0xFF6E6E73);
  static const outline = Color(0x29000000);
  static const scrim = Color(0x7A000000);
  static const primary = Color(0xFF0071E3);
  static const onPrimary = Color(0xFFFFFFFF);
  static const primaryContainer = Color(0xFFE5F1FC);
  static const onPrimaryContainer = Color(0xFF004F9F);
  static const link = Color(0xFF0066CC);
  static const error = Color(0xFFB3261E);
  static const errorContainer = Color(0xFFFCE8E6);
  static const warning = Color(0xFF7A4D00);
  static const warningContainer = Color(0xFFFFF1CC);
  static const success = Color(0xFF1B6E35);
  static const successContainer = Color(0xFFE3F4E7);
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

ThemeData _buildTheme() {
  const scheme = ColorScheme.light(
    primary: Palette.primary,
    onPrimary: Palette.onPrimary,
    primaryContainer: Palette.primaryContainer,
    onPrimaryContainer: Palette.onPrimaryContainer,
    secondary: Palette.link,
    onSecondary: Palette.onPrimary,
    secondaryContainer: Palette.primaryContainer,
    onSecondaryContainer: Palette.onPrimaryContainer,
    error: Palette.error,
    onError: Palette.onPrimary,
    errorContainer: Palette.errorContainer,
    onErrorContainer: Palette.error,
    surface: Palette.surface,
    onSurface: Palette.onSurface,
    onSurfaceVariant: Palette.onSurfaceVariant,
    outline: Palette.outline,
    outlineVariant: Palette.outline,
    scrim: Palette.scrim,
  );

  // Inter has no Devanagari or Gujarati glyphs; these cover Hindi and Gujarati text.
  final fallback = [
    GoogleFonts.notoSansDevanagari().fontFamily!,
    GoogleFonts.notoSansGujarati().fontFamily!,
  ];
  TextStyle style(double size, FontWeight weight, double height, {double spacing = 0}) => GoogleFonts.inter(
        fontSize: size,
        fontWeight: weight,
        height: height,
        letterSpacing: spacing,
        color: Palette.onSurface,
      ).copyWith(fontFamilyFallback: fallback);

  final text = TextTheme(
    headlineMedium: style(28, FontWeight.w600, 1.21, spacing: -0.28), // display
    titleLarge: style(22, FontWeight.w600, 1.27, spacing: -0.11),
    titleMedium: style(17, FontWeight.w600, 1.41),
    bodyLarge: style(17, FontWeight.w400, 1.47),
    bodyMedium: style(15, FontWeight.w400, 1.47),
    labelLarge: style(17, FontWeight.w500, 1.29),
    labelMedium: style(14, FontWeight.w600, 1.29),
    bodySmall: style(12, FontWeight.w400, 1.33), // caption
  );

  OutlineInputBorder fieldBorder(Color color, [double width = 1]) => OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: color, width: width),
      );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Palette.background,
    textTheme: text,
    extensions: const [
      StatusColors(
        muted: Palette.onSurfaceMuted,
        success: Palette.success,
        successContainer: Palette.successContainer,
      ),
    ],
    appBarTheme: AppBarTheme(
      backgroundColor: Palette.surface,
      foregroundColor: Palette.onSurface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: text.titleLarge,
    ),
    dividerTheme: const DividerThemeData(color: Palette.outline, thickness: 1, space: 1),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        shape: const StadiumBorder(),
        textStyle: text.labelLarge,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(48),
        foregroundColor: Palette.link,
        side: const BorderSide(color: Palette.link),
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
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Palette.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      hintStyle: text.bodyLarge!.copyWith(color: Palette.onSurfaceMuted),
      border: fieldBorder(Palette.outline),
      enabledBorder: fieldBorder(Palette.outline),
      focusedBorder: fieldBorder(Palette.primary, 2),
      errorBorder: fieldBorder(Palette.error),
      focusedErrorBorder: fieldBorder(Palette.error, 2),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Palette.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      indicatorColor: Palette.primaryContainer,
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected) ? Palette.primary : Palette.onSurfaceMuted,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => text.labelMedium!.copyWith(
          color: states.contains(WidgetState.selected) ? Palette.primary : Palette.onSurfaceMuted,
        ),
      ),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: Palette.primary,
      foregroundColor: Palette.onPrimary,
      elevation: 0,
      focusElevation: 0,
      hoverElevation: 0,
      highlightElevation: 0,
      shape: StadiumBorder(),
    ),
  );
}
