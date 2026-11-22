import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/loader.dart';
import 'cash_screens.dart';
import '../hire/hire_screens.dart' show PayablesScreen;
import 'owner_screens.dart';
import 'receipt_screens.dart';

typedef _Data = (Map<String, dynamic>, List<Map<String, dynamic>>);

/// Collections: what I hold, the receipts still to collect, and the actions my role allows.
class MoneyScreen extends StatefulWidget {
  const MoneyScreen({super.key});

  @override
  State<MoneyScreen> createState() => _MoneyScreenState();
}

class _MoneyScreenState extends State<MoneyScreen> {
  final _loader = GlobalKey<LoaderState<_Data>>();

  Future<_Data> _load() async {
    final api = context.read<ApiClient>();
    final custody = await api.get('/custody/me') as Map<String, dynamic>;
    final open = (await api.get('/receipts', query: {'status': 'open', 'limit': '200'}) as List).cast<Map<String, dynamic>>();
    return (custody, open);
  }

  Future<void> _open(Widget screen) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
    await _loader.currentState?.reload();
  }

  Widget _action(IconData icon, String title, String subtitle, Widget screen) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: AppCard(
          onTap: () => _open(screen),
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 4),
            leading: Icon(icon, color: Palette.onSurface),
            title: Text(title),
            subtitle: Text(subtitle),
            trailing: const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final user = context.watch<Session>().user!;
    return Scaffold(
      appBar: AppBar(title: const Text('Collections')),
      body: Loader<_Data>(
        key: _loader,
        errorTitle: 'Could not load collections',
        load: _load,
        builder: (context, data) {
          final (custody, open) = data;
          // Receipts with a promise due soonest first, then the oldest.
          open.sort((a, b) => ((a['promised_on'] as String?) ?? '9999').compareTo((b['promised_on'] as String?) ?? '9999'));
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            children: [
              MyCustodyCard(custody: custody),
              const SizedBox(height: 16),
              if (user.canIssueReceipts)
                _action(Icons.receipt_outlined, 'New money receipt', 'For a customer\'s unpaid LRs', const IssueReceiptScreen()),
              if (user.canReceiveCash) ...[
                _action(Icons.move_down, 'Receive a handover', 'Count a collector\'s cash and cheques', const HandoverScreen()),
                _action(Icons.account_balance_outlined, 'Bank deposit', 'Bank what you hold', const DepositScreen()),
              ],
              if (user.canSeeMoneyTrail)
                _action(Icons.insights_outlined, 'Money trail', 'Booked, collected, handed over, banked', const MoneyTrailScreen()),
              if (user.canReconcileBank)
                _action(Icons.upload_file, 'Bank statement', 'Import from ICICI and match', const BankScreen()),
              if (user.can('vendors.pay'))
                _action(Icons.local_shipping_outlined, 'Owed to truck owners', 'Hire still to pay, trip by trip', const PayablesScreen()),
              if (user.canSeeMoneyTrail)
                _action(Icons.hourglass_bottom, 'Where money is stuck', 'Ageing, overdue, limits, late payers', const StuckMoneyScreen()),
              if (user.canManageCredit) ...[
                _action(Icons.report_outlined, 'Shortages', 'Decide what happens to each', const ShortagesScreen()),
                _action(Icons.handshake_outlined, 'Payment terms', 'Advance, at delivery, or credit with a limit', const CreditScreen()),
              ],
              SectionHeader('To collect · ${open.length}', icon: Icons.directions_walk),
              if (open.isEmpty)
                const MessageView(card: true, icon: Icons.check_rounded, tone: Tone.success, title: 'Nothing to collect', body: 'Every money receipt is settled.'),
              for (final r in open)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: ReceiptCard(receipt: r, onTap: () => _open(ReceiptScreen(receiptId: r['id'] as String))),
                ),
            ],
          );
        },
      ),
    );
  }
}
