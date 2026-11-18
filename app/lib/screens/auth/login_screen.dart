import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'auth_scaffold.dart';
import 'forgot_password_screen.dart';
import 'join_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> with Submitter {
  final _login = TextEditingController();
  final _password = TextEditingController();

  @override
  void dispose() {
    _login.dispose();
    _password.dispose();
    super.dispose();
  }

  void _open(Widget screen) => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));

  Future<void> _signIn() async {
    await context.read<Session>().login(_login.text.trim(), _password.text);
    // Tells the phone's password manager the sign-in worked, so it offers to save the password.
    TextInput.finishAutofillContext();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AuthScaffold(
      title: 'Welcome back.',
      subtitle: 'Your freight. Your team. One place.',
      children: [
        AppCard(
          padding: const EdgeInsets.fromLTRB(18, 20, 18, 18),
          child: Form(
            key: formKey,
            child: AutofillGroup(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('Log in to your workspace', style: text.titleLarge!.copyWith(fontSize: 19)),
                  const SizedBox(height: 18),
                  if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 14)],
                  AppTextField(
                    label: 'Email or phone',
                    controller: _login,
                    mandatory: true,
                    hint: 'you@company.com',
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.username, AutofillHints.email],
                  ),
                  AppTextField(
                    label: 'Password',
                    controller: _password,
                    mandatory: true,
                    hint: 'Enter your password',
                    obscure: true,
                    autofillHints: const [AutofillHints.password],
                  ),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton(
                      style: TextButton.styleFrom(padding: EdgeInsets.zero),
                      onPressed: () => _open(ForgotPasswordScreen(login: _login.text.trim())),
                      child: const Text('Forgot password?'),
                    ),
                  ),
                  const SizedBox(height: 8),
                  BusyButton(label: 'Log in', busy: busy, onPressed: () => submit(_signIn)),
                ],
              ),
            ),
          ),
        ),
        AuthNote(
          title: "Can't remember your email?",
          body: 'Find your workspace with the phone number on your account.',
          action: 'Recover email',
          onAction: () => _open(const RecoverEmailScreen()),
        ),
        AuthLink(
          lead: 'New to FreightFlow?',
          action: 'Register or accept an invite',
          onTap: () => _open(const JoinScreen()),
        ),
        const SizedBox(height: 12),
        Text(
          'Secure access for your logistics team.',
          style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
        ),
      ],
    );
  }
}
