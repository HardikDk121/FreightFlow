import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../validation.dart';
import '../../widgets/common.dart';
import 'auth_scaffold.dart';

/// Reset a forgotten password in two steps: ask for a code by email, then enter it with a new password.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key, this.login = ''});

  /// Whatever was typed on the sign-in screen, to save retyping.
  final String login;

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> with Submitter {
  late final _login = TextEditingController(text: widget.login);
  final _code = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _codeSent = false;

  @override
  void dispose() {
    _login.dispose();
    _code.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    await context.read<ApiClient>().post('/auth/password/forgot', {'login': _login.text.trim()}, auth: false);
    if (mounted) setState(() => _codeSent = true);
  }

  Future<void> _reset() async {
    await context.read<ApiClient>().post(
      '/auth/password/reset',
      {'login': _login.text.trim(), 'code': _code.text.trim(), 'new_password': _password.text},
      auth: false,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Password changed. Sign in with the new one.')),
    );
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Forgot password?',
        subtitle: 'A secure way back to your workspace.',
        children: [
          if (_codeSent)
            const AuthSent(
              title: 'Check your inbox',
              body: 'If an account matches, a 6-digit code is on its way. It works once and expires in '
                  '15 minutes. Check your spam folder too.',
            ),
          AppCard(
            padding: const EdgeInsets.fromLTRB(18, 20, 18, 18),
            child: Form(
              key: formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 14)],
                  AppTextField(
                    label: 'Email or phone',
                    controller: _login,
                    mandatory: true,
                    hint: 'you@company.com',
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.username, AutofillHints.email],
                  ),
                  if (_codeSent) ...[
                    AppTextField(
                      label: 'Code from the email',
                      controller: _code,
                      mandatory: true,
                      hint: '6 digits',
                      keyboardType: TextInputType.number,
                      autofillHints: const [AutofillHints.oneTimeCode],
                      check: (v) => RegExp(r'^[0-9]{6}$').hasMatch(v) ? null : 'The code has 6 digits',
                    ),
                    AppTextField(
                      label: 'New password',
                      controller: _password,
                      mandatory: true,
                      hint: 'A phrase of a few words works well',
                      helper: 'At least $minPassword characters. Spaces and any language are fine.',
                      obscure: true,
                      autofillHints: const [AutofillHints.newPassword],
                      check: newPassword,
                    ),
                    AppTextField(
                      label: 'Confirm new password',
                      controller: _confirm,
                      mandatory: true,
                      obscure: true,
                      autofillHints: const [AutofillHints.newPassword],
                      check: (v) => v == _password.text ? null : 'The passwords do not match.',
                    ),
                  ],
                  const SizedBox(height: 4),
                  BusyButton(
                    label: _codeSent ? 'Set new password' : 'Email me a code',
                    busy: busy,
                    onPressed: () => submit(_codeSent ? _reset : _sendCode),
                  ),
                  if (_codeSent)
                    TextButton(
                      onPressed: busy ? null : () => submit(_sendCode),
                      child: const Text('Send another code'),
                    ),
                ],
              ),
            ),
          ),
          const AuthNote(
            title: 'Confirm securely by email',
            body: 'Your new password is applied only with the code sent to your email. Every other '
                'device is signed out.',
          ),
          AuthLink(lead: 'Remembered it?', action: 'Back to log in', onTap: () => Navigator.of(context).maybePop()),
        ],
      );
}

/// For someone who does not remember which email they signed up with.
class RecoverEmailScreen extends StatefulWidget {
  const RecoverEmailScreen({super.key});

  @override
  State<RecoverEmailScreen> createState() => _RecoverEmailScreenState();
}

class _RecoverEmailScreenState extends State<RecoverEmailScreen> with Submitter {
  final _phone = TextEditingController();
  String? _sentMessage;

  @override
  void dispose() {
    _phone.dispose();
    super.dispose();
  }

  Future<void> _recover() async {
    final reply = await context.read<ApiClient>().post(
      '/auth/email/recover',
      {'phone': _phone.text.trim()},
      auth: false,
    ) as Map<String, dynamic>;
    if (mounted) setState(() => _sentMessage = reply['message'] as String);
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Recover email',
        subtitle: 'Find your workspace with your phone.',
        children: [
          if (_sentMessage != null) AuthSent(title: 'Check your phone', body: _sentMessage!),
          AppCard(
            padding: const EdgeInsets.fromLTRB(18, 20, 18, 18),
            child: Form(
              key: formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 14)],
                  AppTextField(
                    label: 'Phone number',
                    controller: _phone,
                    mandatory: true,
                    hint: '+91 phone number',
                    helper: 'Use the phone number linked to your account.',
                    keyboardType: TextInputType.phone,
                    autofillHints: const [AutofillHints.telephoneNumber],
                    check: (v) => RegExp(r'^\+?[0-9]{10,13}$').hasMatch(v.replaceAll(RegExp(r'[\s-]'), ''))
                        ? null
                        : 'Enter 10 to 13 digits',
                  ),
                  const SizedBox(height: 4),
                  BusyButton(label: 'Text me my login email', busy: busy, onPressed: () => submit(_recover)),
                ],
              ),
            ),
          ),
          const AuthNote(
            title: 'Your account stays private.',
            body: 'Account details are never shown here; they go only to the phone on the account. '
                'No phone on your account? Your company admin can see your login email under Team.',
          ),
          AuthLink(lead: 'Found it?', action: 'Back to log in', onTap: () => Navigator.of(context).maybePop()),
        ],
      );
}
