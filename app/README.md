# FreightFlow AI mobile app

Flutter app for slice 1: sign in, register, invites, profile, team, company settings and master data.

**This code has not been compiled or run.** It was written without a Flutter toolchain. Expect to fix
some errors on the first `flutter analyze`.

## First run

```
cd app
flutter create --project-name freightflow --platforms android,ios .
flutter pub get
flutter analyze
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

`flutter create` adds the `android/` and `ios/` folders and keeps the existing `lib/` and `pubspec.yaml`.
`10.0.2.2` is the host machine as seen from the Android emulator. On a real phone, use the machine's LAN
address or the deployed backend URL.

## Android settings to add after `flutter create`

In `android/app/src/main/AndroidManifest.xml`:

- Add `<uses-permission android:name="android.permission.INTERNET"/>` above `<application>`. Debug
  builds have it already; release builds do not.
- While the backend is plain `http`, add `android:usesCleartextTraffic="true"` to `<application>`.
  Remove it once the backend is on HTTPS.

`flutter_secure_storage` needs `minSdkVersion 23` or higher in `android/app/build.gradle`.

## Layout

| Path | Holds |
| --- | --- |
| `lib/theme/app_theme.dart` | Colours, type and component styles from `DESIGN.md` |
| `lib/api/api_client.dart` | HTTP client, token storage, one automatic refresh on 401 |
| `lib/state/session.dart` | Who is signed in; the root widget switches on its status |
| `lib/widgets/common.dart` | Card, chips, fields, empty and error views, the form scaffold |
| `lib/screens/masterdata/resource.dart` | The three master-data resources as data |
| `lib/screens/` | One folder per tab, plus `auth/` |

## Adding a master-data resource

Add one `Resource` to `resource.dart` and list it in `MasterDataScreen._resources`. The list and form
screens are generic.

## Known gaps

- **Fonts.** Inter and the Noto fallbacks load through `google_fonts`, which downloads them on first
  run. Before release, bundle the font files as assets; the package then uses them offline.
- **Package versions** in `pubspec.yaml` are from memory. Run `flutter pub upgrade --major-versions` if
  resolution fails.
- **Language.** The profile stores a language choice, but the interface text is English only.
- **Tabs.** Home, Pending, Scan, Trips and Chat are added as their backend modules are built.
