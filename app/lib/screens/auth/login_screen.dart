import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'accept_invite_screen.dart';
import 'forgot_password_screen.dart';
import 'register_screen.dart';

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
    return Scaffold(
      body: SafeArea(
        child: Form(
          key: formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 56, 16, 16),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(color: Palette.primary, borderRadius: BorderRadius.circular(16)),
                  child: const Icon(Icons.local_shipping_outlined, color: Palette.onPrimary, size: 28),
                ),
              ),
              const SizedBox(height: 20),
              Text('FreightFlow', style: text.headlineMedium),
              const SizedBox(height: 8),
              Text('Sign in to your transport office.', style: text.bodyMedium),
              const SizedBox(height: 32),
              if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 16)],
              AutofillGroup(
                child: Column(
                  children: [
                    AppTextField(
                      label: 'Email or phone',
                      controller: _login,
                      mandatory: true,
                      keyboardType: TextInputType.emailAddress,
                      autofillHints: const [AutofillHints.username, AutofillHints.email],
                    ),
                    AppTextField(
                      label: 'Password',
                      controller: _password,
                      mandatory: true,
                      obscure: true,
                      autofillHints: const [AutofillHints.password],
                    ),
                  ],
                ),
              ),
              FilledButton(
                onPressed: busy ? null : () => submit(_signIn),
                child: busy
                    ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('Sign in'),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  TextButton(
                    onPressed: () => _open(ForgotPasswordScreen(login: _login.text.trim())),
                    child: const Text('Forgot password?'),
                  ),
                  TextButton(
                    onPressed: () => _open(const RecoverEmailScreen()),
                    child: const Text('Forgot email?'),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              const Divider(),
              const SizedBox(height: 16),
              OutlinedButton(
                onPressed: () => _open(const RegisterScreen()),
                child: const Text('Register a new company'),
              ),
              TextButton(
                onPressed: () => _open(const AcceptInviteScreen()),
                child: const Text('I have an invite code'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
