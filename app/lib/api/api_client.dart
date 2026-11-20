import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

/// A failed API call. [status] is the HTTP status, or 0 when the server was unreachable.
class ApiException implements Exception {
  const ApiException(this.status, this.message, {this.code});

  final int status;
  final String message;

  /// The server's error code, such as "credit_hold", when it sent one.
  final String? code;

  @override
  String toString() => message;
}

/// A fresh key for one user action, 32 hex characters.
String newIdempotencyKey() {
  final random = Random.secure();
  return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
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
  static const _uploadTimeout = Duration(seconds: 60);
  static const _offline = ApiException(0, 'Cannot reach the server. Check your connection and try again.');

  final String baseUrl;
  final TokenStore tokens;
  final http.Client _http;
  void Function()? onSessionExpired;
  Future<bool>? _refreshing;

  Future<dynamic> get(String path, {Map<String, String>? query}) async =>
      _json(await _send('GET', path, query: query));

  /// [idempotencyKey]: pass the same key when retrying the same action (a save, a payment), so the
  /// server does it once. Make one with [newIdempotencyKey] when the screen opens.
  Future<dynamic> post(String path, Map<String, dynamic> body, {bool auth = true, String? idempotencyKey}) async =>
      _json(await _send('POST', path, body: body, auth: auth, idempotencyKey: idempotencyKey));

  Future<dynamic> patch(String path, Map<String, dynamic> body) async =>
      _json(await _send('PATCH', path, body: body));

  Future<dynamic> put(String path, Map<String, dynamic> body) async => _json(await _send('PUT', path, body: body));

  /// GET that returns a file, such as a PDF.
  Future<Uint8List> getBytes(String path) async => (await _send('GET', path)).bodyBytes;

  /// POST that returns a file, such as a PDF.
  Future<Uint8List> postForBytes(String path, Map<String, dynamic> body) async =>
      (await _send('POST', path, body: body)).bodyBytes;

  /// Upload one file (a photo, a bank statement) as a multipart form, with any text [fields],
  /// and return the JSON reply.
  Future<dynamic> postFile(String path, Uint8List bytes, String fileName, {Map<String, String> fields = const {}}) async =>
      _json(await _send('POST', path, file: (bytes, fileName), fields: fields));

  /// A multipart form with text [fields] and, optionally, one file sent under [fileField].
  Future<dynamic> postForm(
    String path,
    Map<String, String> fields, {
    (Uint8List, String)? file,
    String fileField = 'file',
    String? idempotencyKey,
  }) async =>
      _json(
        await _send(
          'POST',
          path,
          file: file,
          fileField: fileField,
          fields: fields,
          multipart: true,
          idempotencyKey: idempotencyKey,
        ),
      );

  static dynamic _json(http.Response response) =>
      response.bodyBytes.isEmpty ? null : jsonDecode(utf8.decode(response.bodyBytes));

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
    Map<String, String>? query,
    (Uint8List, String)? file,
    Map<String, String> fields = const {},
    String fileField = 'file',
    bool multipart = false,
    bool auth = true,
    String? idempotencyKey,
    bool retried = false,
  }) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    final http.BaseRequest request;
    if (file != null || multipart) {
      final form = http.MultipartRequest(method, uri)..fields.addAll(fields);
      if (file != null) form.files.add(http.MultipartFile.fromBytes(fileField, file.$1, filename: file.$2));
      request = form;
    } else {
      final json = http.Request(method, uri);
      json.headers['Content-Type'] = 'application/json';
      if (body != null) json.body = jsonEncode(body);
      request = json;
    }
    if (idempotencyKey != null) request.headers['Idempotency-Key'] = idempotencyKey;
    if (auth) {
      final access = await tokens.access;
      if (access != null) request.headers['Authorization'] = 'Bearer $access';
    }

    // An upload waits for the server to read it, so it gets longer.
    final timeout = file == null ? _timeout : _uploadTimeout;
    final http.Response response;
    try {
      final streamed = await _http.send(request).timeout(timeout);
      response = await http.Response.fromStream(streamed).timeout(timeout);
    } on SocketException {
      throw _offline;
    } on http.ClientException {
      throw _offline;
    } on TimeoutException {
      throw _offline;
    } on StateError catch (e) {
      // Android refuses plain-http calls unless the manifest allows cleartext traffic.
      throw ApiException(0, 'Plain-http connection blocked by the phone: ${e.message}');
    }

    if (response.statusCode == 401 && auth) {
      if (!retried && await _refresh()) {
        return _send(
          method,
          path,
          body: body,
          query: query,
          file: file,
          fields: fields,
          fileField: fileField,
          multipart: multipart,
          idempotencyKey: idempotencyKey,
          retried: true,
        );
      }
      await tokens.clear();
      onSessionExpired?.call();
    }
    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, _errorMessage(response), code: _errorCode(response));
    }
    return response;
  }

  /// Concurrent 401s share one refresh call, because a refresh token works only once.
  Future<bool> _refresh() => _refreshing ??= _exchangeRefreshToken().whenComplete(() => _refreshing = null);

  Future<bool> _exchangeRefreshToken() async {
    final refreshToken = await tokens.refresh;
    if (refreshToken == null) return false;
    try {
      final pair = _json(await _send('POST', '/auth/refresh', body: {'refresh_token': refreshToken}, auth: false));
      await tokens.save(pair as Map<String, dynamic>);
      return true;
    } on ApiException catch (e) {
      if (e.status == 0) rethrow; // offline is not a reason to sign the user out
      return false;
    }
  }

  static String? _errorCode(http.Response response) {
    try {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      return data is Map && data['error'] is Map ? data['error']['code'] as String? : null;
    } on FormatException {
      return null;
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
