import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

/// A failed API call. [status] is the HTTP status, or 0 when the server was unreachable.
class ApiException implements Exception {
  const ApiException(this.status, this.message);

  final int status;
  final String message;

  @override
  String toString() => message;
}

class TokenStore {
  const TokenStore([this._storage = const FlutterSecureStorage()]);

  static const _accessKey = 'access_token';
  static const _refreshKey = 'refresh_token';

  final FlutterSecureStorage _storage;

  Future<String?> get access => _storage.read(key: _accessKey);

  Future<String?> get refresh => _storage.read(key: _refreshKey);

  Future<void> save(Map<String, dynamic> tokenPair) async {
    await _storage.write(key: _accessKey, value: tokenPair['access_token'] as String);
    await _storage.write(key: _refreshKey, value: tokenPair['refresh_token'] as String);
  }

  Future<void> clear() async {
    await _storage.delete(key: _accessKey);
    await _storage.delete(key: _refreshKey);
  }
}

/// JSON client for the FreightFlow backend.
///
/// On a 401 it exchanges the refresh token once and repeats the request. If that
/// fails, it clears the stored tokens and calls [onSessionExpired].
class ApiClient {
  ApiClient({required this.baseUrl, required this.tokens, http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  static const _timeout = Duration(seconds: 20);
  static const _offline = ApiException(0, 'Cannot reach the server. Check your connection and try again.');

  final String baseUrl;
  final TokenStore tokens;
  final http.Client _http;
  void Function()? onSessionExpired;
  Future<bool>? _refreshing;

  Future<dynamic> get(String path, {Map<String, String>? query}) => _send('GET', path, query: query);

  Future<dynamic> post(String path, Map<String, dynamic> body, {bool auth = true}) =>
      _send('POST', path, body: body, auth: auth);

  Future<dynamic> patch(String path, Map<String, dynamic> body) => _send('PATCH', path, body: body);

  Future<dynamic> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
    Map<String, String>? query,
    bool auth = true,
    bool retried = false,
  }) async {
    final request = http.Request(method, Uri.parse('$baseUrl$path').replace(queryParameters: query));
    request.headers['Content-Type'] = 'application/json';
    if (auth) {
      final access = await tokens.access;
      if (access != null) request.headers['Authorization'] = 'Bearer $access';
    }
    if (body != null) request.body = jsonEncode(body);

    final http.Response response;
    try {
      final streamed = await _http.send(request).timeout(_timeout);
      response = await http.Response.fromStream(streamed).timeout(_timeout);
    } on SocketException {
      throw _offline;
    } on http.ClientException {
      throw _offline;
    } on TimeoutException {
      throw _offline;
    }

    if (response.statusCode == 401 && auth) {
      if (!retried && await _refresh()) {
        return _send(method, path, body: body, query: query, retried: true);
      }
      await tokens.clear();
      onSessionExpired?.call();
    }
    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, _errorMessage(response));
    }
    return response.bodyBytes.isEmpty ? null : jsonDecode(utf8.decode(response.bodyBytes));
  }

  /// Concurrent 401s share one refresh call, because a refresh token works only once.
  Future<bool> _refresh() => _refreshing ??= _exchangeRefreshToken().whenComplete(() => _refreshing = null);

  Future<bool> _exchangeRefreshToken() async {
    final refreshToken = await tokens.refresh;
    if (refreshToken == null) return false;
    try {
      final pair = await _send('POST', '/auth/refresh', body: {'refresh_token': refreshToken}, auth: false);
      await tokens.save(pair as Map<String, dynamic>);
      return true;
    } on ApiException catch (e) {
      if (e.status == 0) rethrow; // offline is not a reason to sign the user out
      return false;
    }
  }

  static String _errorMessage(http.Response response) {
    try {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is Map && data['error'] is Map) {
        return data['error']['message'] as String;
      }
      if (data is Map && data['detail'] is List) {
        return (data['detail'] as List).map(_validationLine).join('\n');
      }
    } on FormatException {
      // Not JSON: fall through to the generic message.
    }
    return 'Something went wrong (${response.statusCode}).';
  }

  /// One line of a 422 body: `{"loc": ["body", "gstin"], "msg": "Value error, ..."}`.
  static String _validationLine(dynamic item) {
    final loc = (item['loc'] as List).last;
    final message = (item['msg'] as String).replaceFirst('Value error, ', '');
    return loc is String && loc != 'body' ? '$loc: $message' : message;
  }
}
