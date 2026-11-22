import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';

const roleLabels = {
  'admin': 'Owner',
  'manager': 'Manager',
  'dispatcher': 'Dispatcher',
  'clerk': 'Clerk',
  'collector': 'Collector',
  'register_clerk': 'Register clerk',
  'accountant': 'Accountant',
};

/// Every permission the server knows, in plain words. Owner-level ones are marked; only the owner can give them.
const permissionLabels = {
  'lr.book': 'Book LRs',
  'lr.cancel': 'Cancel LRs',
  'lr.settings': 'Change LR numbering and settings',
  'masterdata.edit': 'Edit parties, goods and trucks',
  'dispatch.manage': 'Load and dispatch trucks',
  'dispatch.undo_delivery': 'Undo a trip delivery',
  'gatepass.issue': 'Issue gate passes',
  'delivery.confirm': 'Record proof of delivery',
  'delivery.correct': 'Undo a proof of delivery (owner level)',
  'receipt.issue': 'Issue money receipts',
  'receipt.cancel': 'Cancel unpaid money receipts',
  'collect': 'Collect payments',
  'collect.any_amount': 'Take cash over the collector limit (owner level)',
  'cash.receive': 'Receive cash handovers and bank deposits',
  'money.receivables': 'See who owes what',
  'money.overview': 'See the money trail',
  'bank.reconcile': 'Import and match bank statements (owner level)',
  'credit.manage': 'Set customer credit and approve releases (owner level)',
  'credit.override': 'Book over a credit hold (owner level)',
  'tasks.manage': 'Assign and oversee collection tasks',
  'approvals.request': 'Ask the owner for approvals',
  'approvals.decide': 'Decide approvals (owner level)',
  'dashboard.owner': 'Owner dashboard (owner level)',
  'analytics.view': 'Analytics and reports',
  'vendors.manage': 'Truck owners: hire, expenses, quotes',
  'vendors.pay': 'Pay truck owners',
  'contracts.manage': 'Customer contracts (owner level)',
  'users.manage': 'Manage staff (owner level)',
  'company.settings': 'Change company details',
  'branches.manage': 'Manage branches (owner level)',
  'branches.all': 'See every branch (owner level)',
};

/// A branch picker: all branches, or one. Loads the list itself.
class BranchField extends StatelessWidget {
  const BranchField({super.key, required this.value, required this.onChanged});

  final String? value;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) => FutureBuilder(
        future: context.read<ApiClient>().get('/branches'),
        builder: (context, snapshot) {
          final branches = (snapshot.data as List?)?.cast<Map<String, dynamic>>() ?? const [];
          return ChoiceField<String?>(
            label: 'Branch',
            options: {null: 'All branches', for (final b in branches) b['id'] as String: b['name'] as String},
            value: value,
            onChanged: onChanged,
          );
        },
      );
}

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
        bottomNavigationBar: BottomBar(
          children: [
            BusyButton(icon: Icons.person_add_alt, label: 'Invite staff', onPressed: () => _open(const InviteScreen())),
          ],
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
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        itemCount: users.length + 1,
        separatorBuilder: (_, i) => SizedBox(height: i == 0 ? 0 : 12),
        itemBuilder: (_, i) {
          if (i == 0) return const PageIntro('Everyone who can sign in to this company, and what they can do.');
          final user = users[i - 1];
          return AppCard(
            onTap: () => _open(UserEditScreen(user: user)),
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 22,
                  backgroundColor: user.isActive ? Palette.ink : Palette.disabled,
                  child: Text(
                    user.name.isEmpty ? '?' : user.name[0].toUpperCase(),
                    style: text.titleMedium!.copyWith(color: user.isActive ? Palette.onInk : Palette.onDisabled),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(user.name, style: text.titleMedium),
                      Text(user.email, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
                    ],
                  ),
                ),
                user.isActive
                    ? StatusChip.tone(roleLabels[user.role]!, Tone.info)
                    : StatusChip.tone('Inactive', Tone.neutral),
              ],
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
  String? _branch;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _invite() async {
    final invite = await context.read<ApiClient>().post('/users/invites', {
      'email': _email.text.trim(),
      'role': _role,
      'branch_id': _branch,
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
        subtitle: 'They join with the code you share, in the role you choose.',
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
          BranchField(value: _branch, onChanged: (b) => setState(() => _branch = b)),
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
  late String? _branch = widget.user.branchId;
  late final Set<String> _allowed = {...widget.user.permissions};

  /// What the current role gives without any changes: the starting point the owner's changes are made against.
  late final Set<String> _roleDefaults = {...widget.user.permissions.difference(widget.user.granted.toSet()), ...widget.user.revoked};

  @override
  void dispose() {
    _newPassword.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final api = context.read<ApiClient>();
    final path = '/users/${widget.user.id}';
    final roleChanged = _role != widget.user.role;
    await api.patch(path, {
      'role': _role,
      'is_active': _active,
      'branch_id': _branch,
      // A new role starts from its own defaults; changes are made against the role being kept.
      'permissions_granted': roleChanged ? <String>[] : _allowed.difference(_roleDefaults).toList(),
      'permissions_revoked': roleChanged ? <String>[] : _roleDefaults.difference(_allowed).toList(),
    });
    if (_newPassword.text.isNotEmpty) {
      await api.post('$path/password', {'new_password': _newPassword.text});
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final roleChanged = _role != widget.user.role;
    return FormPage(
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
        if (_role != 'admin') BranchField(value: _branch, onChanged: (b) => setState(() => _branch = b)),
        SwitchField(label: 'Active', value: _active, onChanged: (v) => setState(() => _active = v)),
        AppTextField(label: 'Set a new password', controller: _newPassword, minLength: 8, obscure: true),
        if (_role != 'admin') ...[
          const SectionHeader('What they may do', icon: Icons.lock_outline),
          if (roleChanged)
            Text(
              'Saving gives them the ${roleLabels[_role]} permissions. Adjust them after saving.',
              style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
            )
          else
            AppCard(
              child: Column(
                children: [
                  for (final entry in permissionLabels.entries)
                    CheckboxListTile(
                      dense: true,
                      value: _allowed.contains(entry.key),
                      onChanged: (on) => setState(() => on == true ? _allowed.add(entry.key) : _allowed.remove(entry.key)),
                      title: Text(entry.value, style: text.bodyMedium),
                      subtitle: _roleDefaults.contains(entry.key) != _allowed.contains(entry.key)
                          ? Text('Changed from the role', style: text.bodySmall!.copyWith(color: Palette.warning))
                          : null,
                    ),
                ],
              ),
            ),
        ],
      ],
    );
  }
}
