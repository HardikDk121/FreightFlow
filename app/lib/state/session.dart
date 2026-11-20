import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../widgets/loader.dart';

enum SessionStatus { loading, failed, signedOut, signedIn }

class User {
  const User({
    required this.id,
    required this.name,
    required this.email,
    required this.phone,
    required this.role,
    required this.language,
    required this.isActive,
    required this.branchId,
    required this.permissions,
    required this.granted,
    required this.revoked,
  });

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: json['id'] as String,
        name: json['name'] as String,
        email: json['email'] as String,
        phone: json['phone'] as String?,
        role: json['role'] as String,
        language: json['language'] as String,
        isActive: json['is_active'] as bool,
        branchId: json['branch_id'] as String?,
        permissions: {for (final p in (json['permissions'] as List? ?? const [])) p as String},
        granted: [for (final p in (json['permissions_granted'] as List? ?? const [])) p as String],
        revoked: [for (final p in (json['permissions_revoked'] as List? ?? const [])) p as String],
      );

  final String id;
  final String name;
  final String email;
  final String? phone;
  final String role;
  final String language;
  final bool isActive;

  /// Null: works across all branches.
  final String? branchId;

  /// What this person may do, as worked out by the server. The server checks every action
  /// again, so these only decide what the app offers.
  final Set<String> permissions;
  final List<String> granted;
  final List<String> revoked;

  bool can(String permission) => permissions.contains(permission);

  /// The owner: every permission, every branch.
  bool get isAdmin => role == 'admin';

  bool get canEditMasterData => can('masterdata.edit');

  bool get canBookLr => can('lr.book');

  bool get canCancelLr => can('lr.cancel');

  bool get canSeeMoney => can('money.receivables');

  bool get canSeeMoneyTrail => can('money.overview');

  bool get canIssueReceipts => can('receipt.issue');

  bool get canCollect => can('collect');

  bool get canReceiveCash => can('cash.receive');

  bool get canUndoDelivery => can('dispatch.undo_delivery');

  bool get canDispatch => can('dispatch.manage');

  bool get canIssueGatePass => can('gatepass.issue');

  bool get canConfirmDelivery => can('delivery.confirm');

  bool get canCorrectDelivery => can('delivery.correct');

  bool get canManageTasks => can('tasks.manage');

  bool get canManageCredit => can('credit.manage');

  bool get canReconcileBank => can('bank.reconcile');

  bool get canRequestApproval => can('approvals.request');

  bool get canDecideApproval => can('approvals.decide');

  bool get canManageUsers => can('users.manage');

  bool get canManageBranches => can('branches.manage');

  /// The operations dashboard: the owner's whole business, or a manager's branch.
  bool get seesOperations => can('dashboard.owner') || can('tasks.manage') || can('money.overview');

  /// Anything in the Collections area at all.
  bool get worksWithMoney => canIssueReceipts || canCollect || canReceiveCash;

  /// Anything in the Delivery area: gate passes and proof of delivery.
  bool get worksWithDelivery => canIssueGatePass || canConfirmDelivery;
}

/// Who is signed in. The root widget switches between the auth screens and the app on [status].
class Session extends ChangeNotifier {
  Session(this._api) {
    _api.onSessionExpired = _signedOut;
  }

  final ApiClient _api;

  SessionStatus status = SessionStatus.loading;
  User? user;
  String? startupError;

  /// Called at launch and from the retry button: resume a stored session if there is one.
  Future<void> bootstrap() async {
    status = SessionStatus.loading;
    notifyListeners();
    if (await _api.tokens.access == null) {
      _signedOut();
      return;
    }
    try {
      await _loadUser();
    } on ApiException catch (e) {
      if (e.status == 401) return; // onSessionExpired already signed the user out
      startupError = e.message;
      status = SessionStatus.failed;
      notifyListeners();
    }
  }

  Future<void> login(String login, String password) =>
      _authenticate('/auth/login', {'login': login, 'password': password});

  Future<void> register(Map<String, dynamic> body) => _authenticate('/auth/register', body);

  Future<void> acceptInvite(Map<String, dynamic> body) => _authenticate('/auth/invites/accept', body);

  Future<void> logout() async {
    final refreshToken = await _api.tokens.refresh;
    try {
      if (refreshToken != null) await _api.post('/auth/logout', {'refresh_token': refreshToken});
    } on ApiException {
      // Signing out locally must work offline; the server token expires on its own.
    }
    await _api.tokens.clear();
    _signedOut();
  }

  Future<void> updateProfile(Map<String, dynamic> changes) async {
    user = User.fromJson(await _api.patch('/me', changes) as Map<String, dynamic>);
    notifyListeners();
  }

  /// The server ends every other session and returns a fresh token pair for this one.
  Future<void> changePassword(String current, String next) async {
    final pair = await _api.post('/me/password', {'current_password': current, 'new_password': next});
    await _api.tokens.save(pair as Map<String, dynamic>);
  }

  Future<void> _authenticate(String path, Map<String, dynamic> body) async {
    final pair = await _api.post(path, body, auth: false);
    await _api.tokens.save(pair as Map<String, dynamic>);
    await _loadUser();
  }

  Future<void> _loadUser() async {
    user = User.fromJson(await _api.get('/me') as Map<String, dynamic>);
    status = SessionStatus.signedIn;
    notifyListeners();
  }

  void _signedOut() {
    user = null;
    LoaderState.clearCache();
    status = SessionStatus.signedOut;
    notifyListeners();
  }
}
