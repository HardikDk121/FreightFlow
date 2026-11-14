# FreightFlow project error audit

**Reviewed:** 14 November 2026  
**Scope:** Supplied project source and release APK, plus the three phone screenshots. This is an audit report; application source was not changed.

## Summary

The screenshots show a transport-level failure: the app could not get a response from the API. The same message appears on company registration and invite acceptance. The client maps socket, client, and timeout exceptions to “Cannot reach the server” in `app/lib/api/api_client.dart:51, 82–92`, so this message does not identify the exact network cause.

There are three independent Android/API configuration problems in the supplied build: the release APK has no Internet permission, the Android manifest does not allow the configured plain-HTTP traffic, and the default API host is only correct for an Android emulator. Any one can prevent the phone from reaching the API. The screenshots do not establish which one caused each attempt.

## Confirmed findings

### FF-01 — Release APK is missing Internet permission

**Severity: High — blocks API access in the release build.**

The main manifest, `app/android/app/src/main/AndroidManifest.xml`, does not declare `android.permission.INTERNET`. The permission appears only in the debug and profile manifests. I checked the supplied `app-release.apk` with Android’s `aapt`; its merged manifest contains no `INTERNET` permission. The APK targets Android API 36.

As a result, the supplied release APK cannot make the registration, invite, or other API requests. This is a direct match for the screenshots if they were taken from this release build.

**Fix:** Put `<uses-permission android:name="android.permission.INTERNET"/>` in the main manifest, above `<application>`, so it is included in release builds too.

### FF-02 — Plain HTTP is not enabled in the Android manifest

**Severity: High — likely blocks requests to the configured development API.**

`app/lib/config.dart:3` defaults to `http://10.0.2.2:8000`. The main manifest has no `android:usesCleartextTraffic="true"` attribute or network security configuration. The release APK targets API 36, where cleartext traffic is denied by default. The setup notes in `app/README.md:24–29` also say this setting must be added while the backend uses HTTP, but it is absent from the supplied manifest.

**Fix:** For local development, allow cleartext traffic in the application manifest. For production, serve the API over HTTPS and remove the development-only exception.

### FF-03 — The default API address is emulator-only

**Severity: High for physical-phone testing; conditional on build arguments.**

The app’s default host, `10.0.2.2`, is the Android emulator’s route to the development computer. The app README explicitly says a physical phone needs the computer’s LAN address or a deployed API (`app/README.md:15–20`). The supplied screenshots are from a physical phone. If that APK was built without an `API_BASE_URL` override, it is trying to reach the wrong host.

**Fix:** Use `http://10.0.2.2:8000` on the emulator. On a phone, build with the computer’s reachable LAN address, for example `--dart-define=API_BASE_URL=http://192.168.x.x:8000`, and make sure the phone and computer can reach each other and the host firewall permits port 8000. Use the deployed HTTPS URL for production.

### FF-04 — Flutter analysis fails on the leftover starter widget test

**Severity: Medium — the project’s analyzer/test target is broken.**

Running `dart analyze` in `app/` with the available Dart 3.14.0 SDK reported **19 compile-time errors**, all in `app/test/widget_test.dart`. That file imports `flutter_test` even though it is missing from `app/pubspec.yaml` dev dependencies, imports an unavailable `material_ui` package, and tests the generated counter app by constructing `MyApp`; the actual app root is `FreightFlowApp` in `app/lib/main.dart:26–52`.

There were no analyzer errors under `app/lib/`. The analyzer also reported informational SDK deprecation notices for `flutter/material.dart`; these are not the cause of the network failure.

**Fix:** Add `flutter_test` to `dev_dependencies` and replace the generated counter test with a test for FreightFlow using the app’s actual dependencies. Remove the unused `material_ui` import.

### FF-05 — Registration does not validate email format on the phone

**Severity: Medium — invalid input reaches the server.**

The registration email field sets an email keyboard but no format validator (`app/lib/screens/auth/register_screen.dart:59–64`). The backend requires `EmailStr` (`backend/app/auth/schemas.py:6–11`). The second screenshot shows a non-email value in that field. Once connectivity works, that value will be rejected by the backend instead of being explained before submission.

**Fix:** Add client-side email validation and keep the backend validation as the final check.

### FF-06 — Error banners remain while the user edits the form

**Severity: Low — stale feedback can mislead the next attempt.**

`Submitter` clears its error only when a valid form is submitted again (`app/lib/widgets/common.dart:251–263`). `FormPage` keeps displaying the banner whenever that value is non-null (`app/lib/widgets/common.dart:294–298`). The registration screenshots show the same banner after the form values were changed.

**Fix:** Clear the request error when a field changes, or label it as the result of the previous attempt and clear it on editing.

## Test-input and setup issues

- The invite screenshot uses `admin` as the invite code. Invite acceptance requires the one-time token returned when an administrator creates an invite (`backend/app/users/service.py:48–66`); a placeholder word is not a valid invite. When the server is reachable, the backend returns an invalid/expired/used invite response (`backend/app/auth/service.py:143–153`).
- The screenshots’ invalid email and invite token are separate from the “Cannot reach the server” message. The transport error occurs before the backend can validate those values.
- The project has `.env.example`, but no `.env` was present in the supplied checkout. The README requires copying it and replacing its placeholder values before starting the backend. Docker was not available on this machine, so I could not verify that the backend or database was running.

## Release-readiness items

- `app/android/app/build.gradle.kts:17–19` still uses the placeholder application ID `com.example.freightflow`.
- `app/android/app/build.gradle.kts:32–37` signs release builds with the debug signing key. Configure a unique application ID and proper release signing before publishing.
- `app/README.md:5–6` says the mobile code has not been compiled or run, but the supplied checkout contains a release APK. Update this note so it reflects the current build state.

## Verification performed

- Dart analyzer run on `app/`: 19 errors in the starter test file; no errors under `lib/`.
- Inspected the release APK manifest with `aapt`: target SDK 36 and no Internet permission.
- Found an Android API 37 emulator profile, installed the supplied release APK, and attempted to launch it. Android displayed “System UI isn’t responding” before I could interact with the app, so the emulator run was inconclusive. The emulator was stopped afterward.
- Did not run backend tests or a registration request against a live backend. The local checkout has no configured `.env`, and Docker was unavailable.

## Recommended fix order

1. Add Internet permission to the main manifest and allow HTTP only for development; use HTTPS in production.
2. Set the API URL for the target: emulator host for emulator tests, computer LAN address for the physical phone.
3. Configure and start the backend, then verify its health endpoint from the same device/network.
4. Repair the stale widget test and add local email validation.
5. Clear stale error banners on edit and replace the placeholder invite code with a token generated by the admin invite flow.
6. Replace the placeholder Android application ID and debug release signing before distribution.
