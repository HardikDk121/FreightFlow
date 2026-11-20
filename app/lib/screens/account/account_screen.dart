import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../admin/admin_dashboard_screen.dart' show rateMatrixScreen;
import '../masterdata/master_data_screen.dart';
import '../money/money_screen.dart';
import '../ops/ops_screens.dart';
import '../payments/payments_screens.dart';
import '../team/users_screen.dart';
import 'lr_settings_screen.dart';

const _languages = {'en': 'English', 'hi': 'हिन्दी', 'gu': 'ગુજરાતી'};

class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = context.watch<Session>();
    final user = session.user;
    // The frame between sign-out and the root rebuild has no user.
    if (user == null) return const SizedBox.shrink();
    final text = Theme.of(context).textTheme;

    void open(Widget screen) => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
    final items = <(IconData, String, Widget)>[
      (Icons.person_outline, 'Profile', ProfileScreen(user: user)),
      (Icons.lock_outline, 'Password', const ChangePasswordScreen()),
      (Icons.inventory_2_outlined, 'Master data', MasterDataScreen.masterData()),
      if (user.canEditMasterData) (Icons.price_change_outlined, 'Rate matrix', rateMatrixScreen()),
      if (user.worksWithMoney) (Icons.payments_outlined, 'Collections', const MoneyScreen()),
      if (user.canSeeMoney) (Icons.account_balance_wallet_outlined, 'Receivables', const ReceivablesScreen()),
      if (user.canRequestApproval || user.canDecideApproval) (Icons.how_to_vote_outlined, 'Approvals', const ApprovalsScreen()),
      if (user.canManageUsers) (Icons.group_outlined, 'Team and permissions', const UsersScreen()),
      if (user.canManageBranches) (Icons.account_tree_outlined, 'Branches', const BranchesScreen()),
      if (user.can('company.settings')) (Icons.apartment_outlined, 'Company / LR header', const CompanyScreen()),
      if (user.can('lr.settings')) (Icons.tune, 'LR settings', const LrSettingsScreen()),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
        children: [
          DarkPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Expanded(child: SectionLabel('Your workspace', onDark: true)),
                    StatusChip(
                      roleLabels[user.role]!,
                      background: Palette.primary,
                      foreground: Palette.onPrimary,
                    ),
                  ],
                ),
                Text(user.name, style: onInk(text.headlineMedium!)),
                const SizedBox(height: 4),
                Text(user.email, style: onInk(text.bodyMedium!, muted: true)),
              ],
            ),
          ),
          const SizedBox(height: 16),
          const SectionLabel('Manage'),
          AppCard(
            child: Column(
              children: [
                for (var i = 0; i < items.length; i++) ...[
                  if (i > 0) const Divider(indent: 58, endIndent: 18),
                  ListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 2),
                    leading: Icon(items[i].$1, color: Palette.onSurface),
                    title: Text(items[i].$2, style: text.titleMedium),
                    trailing: const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
                    onTap: () => open(items[i].$3),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: session.logout,
            icon: const Icon(Icons.logout),
            label: const Text('Sign out'),
          ),
          const SizedBox(height: 20),
          Center(
            child: Text(
              'FreightFlow · Built to keep you moving',
              style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
            ),
          ),
        ],
      ),
    );
  }
}

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, required this.user});

  final User user;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> with Submitter {
  late final _name = TextEditingController(text: widget.user.name);
  late final _phone = TextEditingController(text: widget.user.phone ?? '');
  late String _language = widget.user.language;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final phone = _phone.text.trim();
    await context.read<Session>().updateProfile({
      'name': _name.text.trim(),
      'phone': phone.isEmpty ? null : phone,
      'language': _language,
    });
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Profile',
        subtitle: 'How you appear to your team.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Save',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(
            label: 'Name',
            controller: _name,
            mandatory: true,
            capitalization: TextCapitalization.words,
          ),
          AppTextField(
            label: 'Phone',
            controller: _phone,
            keyboardType: TextInputType.phone,
            autofillHints: const [AutofillHints.telephoneNumber],
          ),
          ChoiceField<String>(
            label: 'Language',
            options: _languages,
            value: _language,
            onChanged: (language) => setState(() => _language = language),
          ),
        ],
      );
}

class ChangePasswordScreen extends StatefulWidget {
  const ChangePasswordScreen({super.key});

  @override
  State<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends State<ChangePasswordScreen> with Submitter {
  final _current = TextEditingController();
  final _next = TextEditingController();

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    await context.read<Session>().changePassword(_current.text, _next.text);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Password changed. Other devices were signed out.')),
    );
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => FormPage(
        title: 'Password',
        subtitle: 'Changing it signs out your other devices.',
        formKey: formKey,
        busy: busy,
        error: error,
        submitLabel: 'Change password',
        onSubmit: () => submit(_save),
        children: [
          AppTextField(
            label: 'Current password',
            controller: _current,
            mandatory: true,
            obscure: true,
            autofillHints: const [AutofillHints.password],
          ),
          AppTextField(
            label: 'New password',
            controller: _next,
            mandatory: true,
            minLength: 8,
            obscure: true,
            autofillHints: const [AutofillHints.newPassword],
          ),
        ],
      );
}

/// Admin only. These details are printed as the header of every LR.
class CompanyScreen extends StatefulWidget {
  const CompanyScreen({super.key});

  @override
  State<CompanyScreen> createState() => _CompanyScreenState();
}

class _CompanyScreenState extends State<CompanyScreen> with Submitter {
  final _name = TextEditingController();
  final _tagline = TextEditingController();
  final _address = TextEditingController();
  final _gstin = TextEditingController();
  final _phone = TextEditingController();
  final _bank = TextEditingController();
  bool _loaded = false;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_name, _tagline, _address, _gstin, _phone, _bank]) {
      c.dispose();
    }
    super.dispose();
  }

  static String? _checkAddress(String value) {
    final lines = value.split('\n').where((l) => l.trim().isNotEmpty);
    if (lines.length > 3) return 'Up to 3 lines fit on the LR';
    return lines.any((l) => l.trim().length > 48) ? 'Each line can be up to 48 characters' : null;
  }

  Future<void> _load() async {
    setState(() => _loadError = null);
    try {
      final company = await context.read<ApiClient>().get('/company') as Map<String, dynamic>;
      if (!mounted) return;
      _name.text = company['name'] as String;
      _tagline.text = company['tagline'] as String? ?? '';
      _address.text = company['address'] as String? ?? '';
      _gstin.text = company['gstin'] as String? ?? '';
      _phone.text = company['phone'] as String? ?? '';
      _bank.text = company['bank_details'] as String? ?? '';
      setState(() => _loaded = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  Future<void> _save() async {
    String? orNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
    await context.read<ApiClient>().patch('/company', {
      'name': _name.text.trim(),
      'tagline': orNull(_tagline),
      'address': orNull(_address),
      'gstin': orNull(_gstin),
      'phone': orNull(_phone),
      'bank_details': orNull(_bank),
    });
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return Scaffold(
        appBar: AppBar(title: const Text('Company settings')),
        body: _loadError == null
            ? const SkeletonList()
            : MessageView(
                icon: Icons.cloud_off_outlined,
                title: 'Could not load the company',
                body: _loadError!,
                actionLabel: 'Try again',
                onAction: _load,
              ),
      );
    }
    return FormPage(
      title: 'Company settings',
      subtitle: 'Your identity on every printed receipt.',
      formKey: formKey,
      busy: busy,
      error: error,
      submitLabel: 'Save',
      onSubmit: () => submit(_save),
      children: [
        AppTextField(
          label: 'Company name',
          controller: _name,
          mandatory: true,
          capitalization: TextCapitalization.words,
        ),
        AppTextField(
          label: 'Tagline',
          controller: _tagline,
          capitalization: TextCapitalization.words,
          helper: 'Printed under the name, like “Fleet owners & transport contractors”.',
        ),
        AppTextField(
          label: 'Address',
          controller: _address,
          lines: 3,
          check: _checkAddress,
          capitalization: TextCapitalization.words,
          helper: 'Up to 3 lines of 48 characters, printed top right on the LR.',
        ),
        AppTextField(label: 'GSTIN', controller: _gstin, capitalization: TextCapitalization.characters),
        AppTextField(
          label: 'Contact number',
          controller: _phone,
          keyboardType: TextInputType.phone,
          helper: 'Customers are told to call this number if a payment message looks wrong. Use the owner\'s.',
        ),
        AppTextField(
          label: 'Bank details for payments',
          controller: _bank,
          lines: 4,
          check: (v) {
            final lines = v.split('\n').where((l) => l.trim().isNotEmpty);
            if (lines.length > 4) return 'Up to 4 lines fit on the receipt';
            return lines.any((l) => l.trim().length > 60) ? 'Each line can be up to 60 characters' : null;
          },
          helper: 'Account name, number and IFSC. Printed on every money receipt so customers pay the company, never a person.',
        ),
      ],
    );
  }
}
