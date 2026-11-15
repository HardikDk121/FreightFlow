import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/session.dart';
import '../../widgets/common.dart';

/// Creates a company and its first admin.
class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> with Submitter {
  final _company = TextEditingController();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();

  @override
  void dispose() {
    for (final c in [_company, _name, _email, _phone, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _register() => context.read<Session>().register({
        'company_name': _company.text.trim(),
        'name': _name.text.trim(),
        'email': _email.text.trim(),
        if (_phone.text.trim().isNotEmpty) 'phone': _phone.text.trim(),
        'password': _password.text,
      });

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Register a company',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Create company',
        onSubmit: () => submit(_register),
        children: [
          AppTextField(
            label: 'Company name',
            controller: _company,
            mandatory: true,
            capitalization: TextCapitalization.words,
            autofillHints: const [AutofillHints.organizationName],
          ),
          AppTextField(
            label: 'Your name',
            controller: _name,
            mandatory: true,
            capitalization: TextCapitalization.words,
            autofillHints: const [AutofillHints.name],
          ),
          AppTextField(
            label: 'Email',
            controller: _email,
            mandatory: true,
            keyboardType: TextInputType.emailAddress,
            autofillHints: const [AutofillHints.email],
          ),
          AppTextField(
            label: 'Phone',
            controller: _phone,
            keyboardType: TextInputType.phone,
            autofillHints: const [AutofillHints.telephoneNumber],
          ),
          AppTextField(
            label: 'Password',
            controller: _password,
            mandatory: true,
            minLength: 8,
            obscure: true,
            autofillHints: const [AutofillHints.newPassword],
          ),
        ],
      );
}
