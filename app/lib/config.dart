import 'dart:io';

const _override = String.fromEnvironment('API_BASE_URL');

/// Backend address. Set it at build time:
///   flutter run --dart-define=API_BASE_URL=https://api.example.com
/// Without it, the app targets a backend on the development machine: the Android
/// emulator reaches the host at 10.0.2.2, the iOS simulator at localhost.
final String apiBaseUrl = 'https://freightflow-dev.duckdns.org';
   /// _override.isNotEmpty ? _override : (Platform.isAndroid ? 'http://10.0.2.2:8000' : 'http://localhost:8000');
