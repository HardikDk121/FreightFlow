import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';

/// Proofs of delivery taken while the phone had no connection. Each keeps the time the consignee
/// signed and its own request key, so sending it later records it once, at the right time.
class PodQueue {
  PodQueue(this._api);

  final ApiClient _api;
  static const _key = 'pending_pods';

  Future<List<Map<String, dynamic>>> _read() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    return raw == null ? [] : (jsonDecode(raw) as List).cast<Map<String, dynamic>>();
  }

  Future<void> _write(List<Map<String, dynamic>> items) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, jsonEncode(items));
  }

  Future<int> get count async => (await _read()).length;

  Future<void> add({
    required String gatePassId,
    required String proofJson,
    required String key,
    List<int>? photo,
  }) async {
    final items = await _read();
    items.add({'gate_pass_id': gatePassId, 'proof': proofJson, 'key': key, if (photo != null) 'photo': base64Encode(photo)});
    await _write(items);
  }

  /// Send what is waiting. Ones the server refuses (for example, already delivered) are dropped
  /// with their message; ones that still cannot reach it stay for next time.
  Future<(int sent, List<String> refused)> flush() async {
    final items = await _read();
    final left = <Map<String, dynamic>>[];
    final refused = <String>[];
    var sent = 0;
    for (final item in items) {
      final photo = item['photo'] == null ? null : base64Decode(item['photo'] as String);
      try {
        await _api.postForm(
          '/gate-passes/${item['gate_pass_id']}/delivery',
          {'proof': item['proof'] as String},
          file: photo == null ? null : (photo, 'gate-pass.jpg'),
          fileField: 'photo',
          idempotencyKey: item['key'] as String,
        );
        sent++;
      } on ApiException catch (e) {
        if (e.status == 0) {
          left.add(item);
        } else {
          refused.add(e.message);
        }
      }
    }
    await _write(left);
    return (sent, refused);
  }
}
