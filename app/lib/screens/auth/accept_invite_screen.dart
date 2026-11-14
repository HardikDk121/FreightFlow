import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/session.dart';
import '../../widgets/common.dart';

/// Joins an existing company with the code an admin shared.
class AcceptInviteScreen extends StatefulWidget {
  const AcceptInviteScreen({super.key});

  @override
  State<AcceptInviteScreen> createState() => _AcceptInviteScreenState();
}

class _AcceptInviteScreenState extends State<AcceptInviteScreen> with Submitter {
  final _code = TextEditingController();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();

  @override
  void dispose() {
    for (final c in [_code, _name, _phone, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _accept() => context.read<Session>().acceptInvite({
        'token': _code.text.trim(),
        'name': _name.text.trim(),
        if (_phone.text.trim().isNotEmpty) 'phone': _phone.text.trim(),
        'password': _password.text,
      });

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Join with an invite',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Join company',
        onSubmit: () => submit(_accept),
        children: [
          AppTextField(label: 'Invite code', controller: _code, mandatory: true),
          AppTextField(
            label: 'Your name',
            controller: _name,
            mandatory: true,
            capitalization: TextCapitalization.words,
          ),
          AppTextField(label: 'Phone', controller: _phone, keyboardType: TextInputType.phone),
          AppTextField(label: 'Password', controller: _password, mandatory: true, minLength: 8, obscure: true),
        ],
      );
}
