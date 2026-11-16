import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../widgets/common.dart';

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
  bool _codeSent = false;

  @override
  void dispose() {
    _login.dispose();
    _code.dispose();
    _password.dispose();
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
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Reset password',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: _codeSent ? 'Set new password' : 'Email me a code',
      onSubmit: () => submit(_codeSent ? _reset : _sendCode),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            _codeSent
                ? 'If that account exists, a 6-digit code is on its way to its email. It works once and '
                    'expires in 15 minutes.'
                : 'Enter the email or phone you sign in with. We will email a 6-digit code.',
            style: text.bodyMedium,
          ),
        ),
        AppTextField(
          label: 'Email or phone',
          controller: _login,
          mandatory: true,
          keyboardType: TextInputType.emailAddress,
          autofillHints: const [AutofillHints.username, AutofillHints.email],
        ),
        if (_codeSent) ...[
          AppTextField(
            label: 'Code from the email',
            controller: _code,
            mandatory: true,
            keyboardType: TextInputType.number,
            autofillHints: const [AutofillHints.oneTimeCode],
            check: (v) => RegExp(r'^[0-9]{6}$').hasMatch(v) ? null : 'The code has 6 digits',
          ),
          AppTextField(
            label: 'New password',
            controller: _password,
            mandatory: true,
            minLength: 8,
            obscure: true,
            autofillHints: const [AutofillHints.newPassword],
          ),
          TextButton(
            onPressed: busy ? null : () => submit(_sendCode),
            child: const Text('Send another code'),
          ),
        ],
      ],
    );
  }
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
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return FormPage(
      title: 'Find my login email',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Text it to my phone',
      onSubmit: () => submit(_recover),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            'Enter the phone number on your account. Your login email is sent to that phone by SMS, '
            'and is never shown here.',
            style: text.bodyMedium,
          ),
        ),
        AppTextField(
          label: 'Phone number',
          controller: _phone,
          mandatory: true,
          keyboardType: TextInputType.phone,
          autofillHints: const [AutofillHints.telephoneNumber],
          check: (v) =>
              RegExp(r'^\+?[0-9]{10,13}$').hasMatch(v.replaceAll(RegExp(r'[\s-]'), '')) ? null : 'Enter 10 to 13 digits',
        ),
        if (_sentMessage != null)
          AppCard(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(_sentMessage!, style: text.bodyMedium),
            ),
          ),
        Padding(
          padding: const EdgeInsets.only(top: 16),
          child: Text(
            'No phone on your account? Your company admin can see your login email under Team.',
            style: text.bodyMedium,
          ),
        ),
      ],
    );
  }
}
