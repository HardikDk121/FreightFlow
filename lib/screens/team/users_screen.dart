import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';

const roleLabels = {'admin': 'Admin', 'manager': 'Manager', 'dispatcher': 'Dispatcher', 'clerk': 'Clerk'};

/// Admin only: everyone in the company, with invite and edit.
class UsersScreen extends StatefulWidget {
  const UsersScreen({super.key});

  @override
  State<UsersScreen> createState() => _UsersScreenState();
}

class _UsersScreenState extends State<UsersScreen> {
  List<User>? _users;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _users = null;
      _error = null;
    });
    try {
      final data = await context.read<ApiClient>().get('/users') as List;
      if (!mounted) return;
      setState(() => _users = [for (final u in data) User.fromJson(u as Map<String, dynamic>)]);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _open(Widget screen) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => screen));
    if (changed == true && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Team')),
        floatingActionButton: FloatingActionButton.extended(
          heroTag: 'invite',
          onPressed: () => _open(const InviteScreen()),
          icon: const Icon(Icons.person_add_alt),
          label: const Text('Invite'),
        ),
        body: _body(),
      );

  Widget _body() {
    if (_error != null) {
      return MessageView(
        icon: Icons.cloud_off_outlined,
        title: 'Could not load the team',
        body: _error!,
        actionLabel: 'Try again',
        onAction: _load,
      );
    }
    final users = _users;
    if (users == null) return const SkeletonList();
    final text = Theme.of(context).textTheme;
    final status = StatusColors.of(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
        itemCount: users.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, i) {
          final user = users[i];
          return AppCard(
            child: ListTile(
              minVerticalPadding: 16,
              title: Text(user.name, style: text.titleMedium),
              subtitle: Text(user.email, style: text.bodyMedium),
              trailing: user.isActive
                  ? StatusChip(
                      roleLabels[user.role]!,
                      background: Palette.primaryContainer,
                      foreground: Palette.onPrimaryContainer,
                    )
                  : StatusChip('Inactive', background: Palette.background, foreground: status.muted),
              onTap: () => _open(UserEditScreen(user: user)),
            ),
          );
        },
      ),
    );
  }
}

/// Creates an invite and shows its code once, for the admin to share.
class InviteScreen extends StatefulWidget {
  const InviteScreen({super.key});

  @override
  State<InviteScreen> createState() => _InviteScreenState();
}

class _InviteScreenState extends State<InviteScreen> with Submitter {
  final _email = TextEditingController();
  String _role = 'clerk';

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _invite() async {
    final invite = await context.read<ApiClient>().post('/users/invites', {
      'email': _email.text.trim(),
      'role': _role,
    }) as Map<String, dynamic>;
    if (!mounted) return;
    final code = invite['token'] as String;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Invite code'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Share this code with the new staff member. It works once, for 3 days, and is not shown again.',
            ),
            const SizedBox(height: 16),
            SelectableText(code),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Clipboard.setData(ClipboardData(text: code)),
            child: const Text('Copy'),
          ),
          TextButton(onPressed: () => Navigator.of(dialogContext).pop(), child: const Text('Done')),
        ],
      ),
    );
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Invite staff',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Create invite',
        onSubmit: () => submit(_invite),
        children: [
          AppTextField(
            label: 'Email',
            controller: _email,
            mandatory: true,
            keyboardType: TextInputType.emailAddress,
          ),
          ChoiceField<String>(
            label: 'Role',
            options: roleLabels,
            value: _role,
            onChanged: (role) => setState(() => _role = role),
          ),
        ],
      );
}

/// Change a user's role, switch them off, or set a new password for them.
class UserEditScreen extends StatefulWidget {
  const UserEditScreen({super.key, required this.user});

  final User user;

  @override
  State<UserEditScreen> createState() => _UserEditScreenState();
}

class _UserEditScreenState extends State<UserEditScreen> with Submitter {
  final _newPassword = TextEditingController();
  late String _role = widget.user.role;
  late bool _active = widget.user.isActive;

  @override
  void dispose() {
    _newPassword.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final api = context.read<ApiClient>();
    final path = '/users/${widget.user.id}';
    if (_role != widget.user.role || _active != widget.user.isActive) {
      await api.patch(path, {'role': _role, 'is_active': _active});
    }
    if (_newPassword.text.isNotEmpty) {
      await api.post('$path/password', {'new_password': _newPassword.text});
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: widget.user.name,
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          ChoiceField<String>(
            label: 'Role',
            options: roleLabels,
            value: _role,
            onChanged: (role) => setState(() => _role = role),
          ),
          SwitchField(label: 'Active', value: _active, onChanged: (v) => setState(() => _active = v)),
          AppTextField(label: 'Set a new password', controller: _newPassword, minLength: 8, obscure: true),
        ],
      );
}
