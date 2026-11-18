import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/session.dart';
import '../../widgets/common.dart';
import 'auth_scaffold.dart';

/// Register a new company, or join an existing one with an invite code.
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

  @override
  void dispose() {
    for (final c in [_company, _code, _name, _email, _phone, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  /// The first person to sign up creates the company and becomes its admin; everyone else joins
  /// by invite, which carries their company and role.
  Future<void> _join() {
    final session = context.read<Session>();
    final phone = _phone.text.trim();
    if (_invite) {
      return session.acceptInvite({
        'token': _code.text.trim(),
        'name': _name.text.trim(),
        if (phone.isNotEmpty) 'phone': phone,
        'password': _password.text,
      });
    }
    return session.register({
      'company_name': _company.text.trim(),
      'name': _name.text.trim(),
      'email': _email.text.trim(),
      if (phone.isNotEmpty) 'phone': phone,
      'password': _password.text,
    });
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
                      ),
                    AppTextField(
                      label: 'Full name',
                      controller: _name,
                      mandatory: true,
                      hint: 'Your name',
                      capitalization: TextCapitalization.words,
                      autofillHints: const [AutofillHints.name],
                    ),
                    if (!_invite)
                      AppTextField(
                        label: 'Work email',
                        controller: _email,
                        mandatory: true,
                        hint: 'you@company.com',
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [AutofillHints.email],
                      ),
                    AppTextField(
                      label: 'Phone',
                      controller: _phone,
                      hint: '+91 phone number',
                      keyboardType: TextInputType.phone,
                      autofillHints: const [AutofillHints.telephoneNumber],
                      helper: 'Lets you recover your login email by SMS.',
                    ),
                    AppTextField(
                      label: 'Password',
                      controller: _password,
                      mandatory: true,
                      minLength: 8,
                      hint: 'Create a strong password',
                      helper: 'Use at least 8 characters.',
                      obscure: true,
                      autofillHints: const [AutofillHints.newPassword],
                    ),
                    const SizedBox(height: 4),
                    BusyButton(
                      label: _invite ? 'Join company' : 'Create account',
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
