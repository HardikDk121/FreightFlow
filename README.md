# FreightFlow AI mobile app

Flutter app: sign in, LRs with invoice scan and printing, pending goods, truck loading, trips and delivery, chat, dashboard, and the account, team and master-data screens.

**This code has not been compiled or run.** It was written without a Flutter toolchain. Expect to fix
some errors on the first `flutter analyze`.

## First run

```
cd app
flutter create --project-name freightflow --platforms android,ios .
flutter pub get
flutter analyze
flutter run
```

`flutter create` adds the `android/` and `ios/` folders and keeps the existing `lib/` and `pubspec.yaml`.
With no `API_BASE_URL`, the app looks for the backend on the development machine: `10.0.2.2:8000` from the
Android emulator, `localhost:8000` from the iOS simulator. On a real phone, pass the machine's LAN address
or the deployed URL: `flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000`.

## Android settings to add after `flutter create`

In `android/app/src/main/AndroidManifest.xml`:

- Add `<uses-permission android:name="android.permission.INTERNET"/>` above `<application>`. Debug
  builds have it already; release builds do not.
- While the backend is plain `http`, add `android:usesCleartextTraffic="true"` to `<application>`.
  Remove it once the backend is on HTTPS.

`flutter_secure_storage` needs `minSdkVersion 23` or higher in `android/app/build.gradle`.

## iOS

One codebase builds both platforms; nothing in `lib/` is Android-specific.

- Building for iOS needs a Mac with Xcode. Run `cd ios && pod install` once, then `flutter run` with a
  simulator open.
- While the backend is plain `http`, add this to `ios/Runner/Info.plist`, and remove it once the backend
  is on HTTPS:

  ```
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsArbitraryLoads</key><true/></dict>
  ```

- Running on a real iPhone or publishing to TestFlight or the App Store needs a paid Apple Developer
  account.

### Camera access for invoice scanning

Add these two keys to `ios/Runner/Info.plist`, or the app closes when the camera opens on an iPhone:

```
<key>NSCameraUsageDescription</key>
<string>Photograph invoices to fill the LR.</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>Choose an invoice photo to fill the LR.</string>
```

Android needs nothing extra.

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
- **Navigation.** Five tabs: Home, LRs, Pending, Trips, Ask. Account, Team and Master data open from the icon on Home.
