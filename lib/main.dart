import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'config.dart';
import 'screens/auth/login_screen.dart';
import 'screens/shell.dart';
import 'state/session.dart';
import 'theme/app_theme.dart';
import 'widgets/common.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // A widget that fails to build says what went wrong, instead of leaving a blank grey area.
  ErrorWidget.builder = (details) => Container(
        color: Palette.errorContainer,
        padding: const EdgeInsets.all(16),
        child: Text(
          'This part of the screen hit a problem:\n${details.exceptionAsString()}',
          textDirection: TextDirection.ltr,
          style: const TextStyle(color: Palette.error, fontSize: 13),
        ),
      );
  final api = ApiClient(baseUrl: apiBaseUrl, tokens: const TokenStore());
  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<Session>(create: (_) => Session(api)..bootstrap()),
      ],
      child: const FreightFlowApp(),
    ),
  );
}

class FreightFlowApp extends StatelessWidget {
  const FreightFlowApp({super.key});

  @override
  Widget build(BuildContext context) {
    final session = context.watch<Session>();
    return MaterialApp(
      // A new key on sign-in and sign-out discards every pushed route.
      key: ValueKey(session.status == SessionStatus.signedIn),
      title: 'FreightFlow',
      debugShowCheckedModeBanner: false,
      theme: appTheme,
      home: switch (session.status) {
        SessionStatus.loading => const Scaffold(body: Center(child: CircularProgressIndicator())),
        SessionStatus.failed => Scaffold(
            body: MessageView(
              icon: Icons.cloud_off_outlined,
              title: 'Could not start',
              body: session.startupError!,
              actionLabel: 'Try again',
              onAction: session.bootstrap,
            ),
          ),
        SessionStatus.signedOut => const LoginScreen(),
        SessionStatus.signedIn => const Shell(),
      },
    );
  }
}
