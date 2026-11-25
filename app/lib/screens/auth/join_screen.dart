import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../validation.dart';
import '../../widgets/common.dart';
import '../../widgets/phone_field.dart';
import 'auth_scaffold.dart';

/// Register a new company, or join an existing one with an invite code.
///
/// Registering proves the email address first when the server asks for it: a 6-digit code is
/// emailed, valid for 10 minutes, and a new one can be asked for after a minute.
class JoinScreen extends StatefulWidget {
  const JoinScreen({super.key});

  @override
  State<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends State<JoinScreen> with Submitter {
  bool _invite = false;
  final _company = TextEditingController();
  final _code = TextEditingController();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  final _emailCode = TextEditingController();

  /// Set once the server has emailed a code for [_codeFor]; null while no code is needed yet.
  String? _codeFor;
  int _resendIn = 0;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    for (final c in [_company, _code, _name, _email, _phone, _password, _confirm, _emailCode]) {
      c.dispose();
    }
    super.dispose();
  }

  void _countDown(int seconds) {
    _timer?.cancel();
    setState(() => _resendIn = seconds);
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      setState(() => _resendIn = _resendIn > 0 ? _resendIn - 1 : 0);
      if (_resendIn == 0) t.cancel();
    });
  }

  /// Ask for an email code. Returns false when the server does not need one.
  Future<bool> _sendCode() async {
    final email = _email.text.trim();
    final sent = await context.read<ApiClient>().post('/auth/register/code', {'email': email}, auth: false) as Map<String, dynamic>;
    if (sent['required'] != true) return false;
    setState(() => _codeFor = email);
    _countDown(sent['resend_after'] as int? ?? 60);
    return true;
  }

  Future<void> _join() async {
    final session = context.read<Session>();
    final phone = _phone.text.trim();
    if (_invite) {
      return session.acceptInvite({
        'token': _code.text.trim(),
        'name': tidy(_name.text),
        if (phone.isNotEmpty) 'phone': phone,
        'password': _password.text,
      });
    }
    // The email changed after a code was sent: the old code is for the old address.
    if (_codeFor != null && _codeFor != _email.text.trim()) {
      setState(() => _codeFor = null);
      _emailCode.clear();
    }
    if (_codeFor == null && await _sendCode()) return; // the code field now shows; the person types it next
    return session.register({
      'company_name': tidy(_company.text),
      'name': tidy(_name.text),
      'email': _email.text.trim(),
      if (phone.isNotEmpty) 'phone': phone,
      'password': _password.text,
      if (_codeFor != null) 'email_code': _emailCode.text.trim(),
    });
  }

  Future<void> _resend() async {
    try {
      await _sendCode();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('A new code is on its way.')));
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Join your team.',
        subtitle: 'Register a company, or use the invite your admin sent.',
        children: [
          AppCard(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
            child: Form(
              key: formKey,
              autovalidateMode: AutovalidateMode.onUserInteraction,
              onChanged: () {
                if (error != null) setState(() => error = null);
              },
              child: AutofillGroup(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Segmented<bool>(
                      options: const {false: 'Register', true: 'Accept invite'},
                      value: _invite,
                      onChanged: (v) => setState(() {
                        _invite = v;
                        error = null;
                      }),
                    ),
                    const SizedBox(height: 18),
                    if (error != null) ...[ErrorBanner(error!), const SizedBox(height: 14)],
                    if (_invite)
                      AppTextField(
                        label: 'Invite code',
                        controller: _code,
                        mandatory: true,
                        hint: 'Paste the code you were sent',
                        helper: 'Your company and role come from the invite.',
                      )
                    else
                      AppTextField(
                        label: 'Company name',
                        controller: _company,
                        mandatory: true,
                        hint: 'e.g. Sharma Logistics',
                        capitalization: TextCapitalization.words,
                        autofillHints: const [AutofillHints.organizationName],
                        helper: 'You become its admin and can invite your team.',
                        check: businessName,
                      ),
                    AppTextField(
                      label: 'Full name',
                      controller: _name,
                      mandatory: true,
                      hint: 'Your name',
                      capitalization: TextCapitalization.words,
                      autofillHints: const [AutofillHints.name],
                      check: personName,
                    ),
                    if (!_invite)
                      AppTextField(
                        label: 'Work email',
                        controller: _email,
                        mandatory: true,
                        hint: 'you@company.com',
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [AutofillHints.email],
                        check: (v) => RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(v) ? null : 'Enter a valid email address.',
                      ),
                    PhoneField(controller: _phone, helper: 'Lets you recover your login email by SMS.'),
                    AppTextField(
                      label: 'Password',
                      controller: _password,
                      mandatory: true,
                      hint: 'A phrase of a few words works well',
                      helper: 'At least $minPassword characters. Spaces and any language are fine.',
                      obscure: true,
                      autofillHints: const [AutofillHints.newPassword],
                      check: newPassword,
                    ),
                    AppTextField(
                      label: 'Confirm password',
                      controller: _confirm,
                      mandatory: true,
                      obscure: true,
                      autofillHints: const [AutofillHints.newPassword],
                      check: (v) => v == _password.text ? null : 'The passwords do not match.',
                    ),
                    if (!_invite && _codeFor != null) ...[
                      AppTextField(
                        label: 'Code from your email',
                        controller: _emailCode,
                        mandatory: true,
                        hint: '6 digits',
                        keyboardType: TextInputType.number,
                        autofillHints: const [AutofillHints.oneTimeCode],
                        helper: 'Sent to $_codeFor. It works for 10 minutes.',
                        check: (v) => RegExp(r'^[0-9]{6}$').hasMatch(v) ? null : 'Enter the 6 digits.',
                      ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton(
                          onPressed: _resendIn > 0 ? null : _resend,
                          child: Text(_resendIn > 0 ? 'Send a new code in $_resendIn s' : 'Send a new code'),
                        ),
                      ),
                    ],
                    const SizedBox(height: 4),
                    BusyButton(
                      label: _invite ? 'Join company' : (_codeFor == null ? 'Create account' : 'Verify and create account'),
                      busy: busy,
                      onPressed: () => submit(_join),
                    ),
                  ],
                ),
              ),
            ),
          ),
          AuthLink(lead: 'Already registered?', action: 'Log in', onTap: () => Navigator.of(context).maybePop()),
        ],
      );
}
