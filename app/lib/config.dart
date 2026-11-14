/// Override at build time: flutter run --dart-define=API_BASE_URL=https://api.example.com
/// The default reaches a backend on the host machine from the Android emulator.
const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://10.0.2.2:8000');
