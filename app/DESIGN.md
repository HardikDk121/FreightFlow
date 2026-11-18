# FreightFlow app design

The visual language, taken from the Figma screens (Group 4) and adapted for the whole app. Tokens live
in `lib/theme/app_theme.dart`; reusable pieces in `lib/widgets/common.dart`. Use those rather than
styling a screen by hand.

## Principles

- **Two brand surfaces.** Near-black ink carries headers, the navigation bar, selected states and one
  key fact per screen. Amber is a fill behind dark text: the primary button, the active tab, meters.
- **Amber is never text or a thin icon on white.** It is too light to read there. On ink it is fine.
- **Flat.** Depth comes from white cards on a light grey page, not shadows. The floating navigation
  bar is the one exception.
- **One primary action per screen,** pinned at the bottom.
- **Status is a word in a pill,** never colour alone.

## Colour

| Token | Hex | Use |
| --- | --- | --- |
| `background` | #F5F5F7 | Page |
| `surface` | #FFFFFF | Cards, fields |
| `onSurface` | #14141A | Text |
| `onSurfaceVariant` | #4A4A55 | Field labels |
| `onSurfaceMuted` | #6B6B76 | Secondary text |
| `outline` | #E4E4EA | Field borders, dividers |
| `ink` / `inkRaised` | #14141A / #24242D | Hero bands, dark cards, navigation, selected chips |
| `onInk` / `onInkMuted` | #FFFFFF / #B4B4BF | Text on ink |
| `primary` | #F5B82E | Primary buttons, active tab, meters, focus ring |
| `onPrimary` | #14141A | Text on amber |
| `primaryContainer` / `onPrimaryContainer` | #FFF1CF / #6B4A00 | Neutral-positive pills (amounts, roles), app-filled fields |
| `success` pair | #E2F5E6 / #1E7A3A | Valid, delivered, all clear |
| `warning` pair | #FFE9D4 / #8F4300 | Waiting too long, part delivered |
| `error` pair | #FDE6E1 / #B42318 | Missing, expired, failed |
| `danger` | #C4320A | Destructive buttons (white text) |

Pills use the `Tone` enum: `neutral`, `info`, `success`, `warning`, `danger`, `dark`.

## Type

Plus Jakarta Sans, with Noto Sans Devanagari and Gujarati as fallbacks.

| Style | Size / weight | Use |
| --- | --- | --- |
| `displaySmall` | 32 / 800 | Hero titles, LR number |
| `headlineMedium` | 26 / 800 | Big figures |
| `titleLarge` | 22 / 800 | Screen titles, card headlines |
| `titleMedium` | 16 / 700 | Card titles, list rows |
| `bodyLarge` / `bodyMedium` | 16 / 14, 500 | Field text / body |
| `labelLarge` | 15 / 700 | Buttons |
| `labelMedium` | 13 / 600 | Field labels, chips |
| `labelSmall` | 11 / 700, spaced | Upper-case section labels |
| `bodySmall` | 12 / 500 | Helper lines, timestamps |

## Shape and spacing

Cards 22, fields 14, buttons and chips fully round. Page margin 20; gap between cards 12; card padding
16 to 20. Touch targets at least 44.

## Components

| Widget | What it is |
| --- | --- |
| `HeroHeader` | Dark band: optional back, wordmark or trailing action, eyebrow, big title, line, and a child such as a route card |
| `AppCard` / `DarkPanel` | White or ink rounded surface; tappable when given `onTap` |
| `StatusChip.tone` | Pill with a word |
| `Segmented` | Grey track, chosen option in ink: tabs, filters, register/invite |
| `MetricTile`, `MeterBar` | Big figure with label; amber progress on ink |
| `SectionHeader`, `SectionLabel`, `PageIntro` | Section title with icon; upper-case label; one line under a title |
| `AppTextField`, `PickerField`, `ChoiceField`, `SwitchField` | Form inputs, all with the label above |
| `FormPage` | Form screen: optional `hero`, `subtitle`, pinned primary and optional secondary button |
| `BusyButton` | Primary button with spinner |
| `MessageView` | Empty and error states, full screen or as a card |
| `AuthScaffold` | Sign-in family: dark band with the white card overlapping it |

## Deliberate departures from the Figma frames

- **No illustrations.** The 3D box, checkmark and isometric map are artwork the app does not have.
  Empty states use an icon in a tinted circle instead.
- **No "Live map" or "Synced".** There is no GPS feed; the trip screen shows a stop-by-stop timeline.
- **Home shows today's figures** in a dark card instead of the decorative map.
- **New LR keeps package types** instead of free L × W × H boxes, because the planner and freight
  calculation use the item master.
- **Register includes the company name,** which the server needs, and passwords stay at 8 characters
  minimum, matching the server.
