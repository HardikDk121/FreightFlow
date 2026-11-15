import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../masterdata/master_data_screen.dart';
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
    Widget tile(IconData icon, String label, VoidCallback onTap) => ListTile(
          leading: Icon(icon, color: Palette.onSurfaceVariant),
          title: Text(label, style: text.bodyLarge),
          trailing: const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
          onTap: onTap,
        );

    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          AppCard(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(user.name, style: text.titleMedium),
                        const SizedBox(height: 4),
                        Text(user.email, style: text.bodyMedium),
                      ],
                    ),
                  ),
                  StatusChip(
                    roleLabels[user.role]!,
                    background: Palette.primaryContainer,
                    foreground: Palette.onPrimaryContainer,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          AppCard(
            child: Column(
              children: [
                tile(Icons.badge_outlined, 'Edit profile', () => open(ProfileScreen(user: user))),
                const Divider(indent: 16, endIndent: 16),
                tile(Icons.lock_outline, 'Change password', () => open(const ChangePasswordScreen())),
                const Divider(indent: 16, endIndent: 16),
                tile(Icons.inventory_2_outlined, 'Master data', () => open(const MasterDataScreen())),
                if (user.isAdmin) ...[
                  const Divider(indent: 16, endIndent: 16),
                  tile(Icons.group_outlined, 'Team', () => open(const UsersScreen())),
                  const Divider(indent: 16, endIndent: 16),
                  tile(Icons.apartment_outlined, 'Company and LR header', () => open(const CompanyScreen())),
                  const Divider(indent: 16, endIndent: 16),
                  tile(Icons.receipt_long_outlined, 'LR settings', () => open(const LrSettingsScreen())),
                ],
              ],
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton(onPressed: session.logout, child: const Text('Sign out')),
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
        title: 'Edit profile',
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
        title: 'Change password',
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
  bool _loaded = false;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_name, _tagline, _address, _gstin, _phone]) {
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
        AppTextField(label: 'Contact number', controller: _phone, keyboardType: TextInputType.phone),
      ],
    );
  }
}
