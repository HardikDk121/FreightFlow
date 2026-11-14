import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/session.dart';
import '../../widgets/common.dart';
import 'accept_invite_screen.dart';
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

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Form(
            key: formKey,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 48, 16, 16),
              children: [
                Text('FreightFlow', style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 8),
                Text('Sign in to your transport office.', style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(height: 32),
                if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 16)],
                AppTextField(
                  label: 'Email or phone',
                  controller: _login,
                  mandatory: true,
                  keyboardType: TextInputType.emailAddress,
                ),
                AppTextField(label: 'Password', controller: _password, mandatory: true, obscure: true),
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: busy
                      ? null
                      : () => submit(() => context.read<Session>().login(_login.text.trim(), _password.text)),
                  child: busy
                      ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Sign in'),
                ),
                const SizedBox(height: 12),
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
