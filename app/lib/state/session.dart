import 'package:flutter/foundation.dart';

import '../api/api_client.dart';

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
  });

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: json['id'] as String,
        name: json['name'] as String,
        email: json['email'] as String,
        phone: json['phone'] as String?,
        role: json['role'] as String,
        language: json['language'] as String,
        isActive: json['is_active'] as bool,
      );

  final String id;
  final String name;
  final String email;
  final String? phone;
  final String role;
  final String language;
  final bool isActive;

  bool get isAdmin => role == 'admin';

  bool get canEditMasterData => role == 'admin' || role == 'manager';

  bool get canBookLr => role == 'admin' || role == 'manager' || role == 'clerk';

  bool get canCancelLr => role == 'admin' || role == 'manager';

  /// Receivables and other money views.
  bool get canSeeMoney => role == 'admin' || role == 'manager';

  bool get canUndoDelivery => role == 'admin' || role == 'manager';

  bool get canDispatch => role == 'admin' || role == 'manager' || role == 'dispatcher';
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
    status = SessionStatus.signedOut;
    notifyListeners();
  }
}
