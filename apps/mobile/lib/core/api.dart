import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';
import 'guest.dart';
import 'models.dart';

/// A failure the user can be told about without leaking internals.
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

/// The transport boundary.
///
/// Declared as an interface so screens depend on behaviour rather than on
/// `http`, and so widget tests run with no network.
abstract interface class MeditationApi {
  Future<Recommendation> recommend(CheckIn checkIn);

  Future<CheckInReceipt> submitCheckIn(CheckIn checkIn);

  Future<MeditationSession> createSession(String checkInId);

  Future<void> startSession(String sessionId);

  Future<void> submitFeedback(String sessionId, SessionFeedback feedback);

  /// This guest's sessions from the backend, newest first.
  Future<SessionHistoryPage> sessionHistory({String? cursor, int limit});

  /// Deletes everything the backend holds for this guest.
  Future<void> deleteMyData();

  /// Everything the backend holds for this guest, as JSON.
  Future<Map<String, dynamic>> exportMyData();
}

class HttpMeditationApi implements MeditationApi {
  HttpMeditationApi({
    required AppConfig config,
    required GuestIdentity guest,
    http.Client? client,
  }) : _config = config,
       _guest = guest,
       _client = client ?? http.Client();

  static const String guestHeader = 'X-Guest-Id';

  final AppConfig _config;
  final GuestIdentity _guest;
  final http.Client _client;
  static const Duration _timeout = Duration(seconds: 15);

  Uri _uri(String path) => Uri.parse('${_config.apiBaseUrl}$path');

  Future<Map<String, String>> _headers() async => <String, String>{
    'content-type': 'application/json',
    'accept': 'application/json',
    // The guest's own identifier, sent only to this backend. It is what makes
    // history, export and deletion possible without an account.
    guestHeader: await _guest.ensure(),
  };

  @override
  Future<Recommendation> recommend(CheckIn checkIn) async {
    final Map<String, dynamic> body = await _postJson(
      '/v1/recommendations',
      checkIn.toJson(),
      expected: 200,
    );
    return Recommendation.fromJson(body);
  }

  @override
  Future<CheckInReceipt> submitCheckIn(CheckIn checkIn) async {
    final Map<String, dynamic> body = await _postJson(
      '/v1/check-ins',
      checkIn.toJson(),
      expected: 201,
    );
    return CheckInReceipt.fromJson(body, checkIn);
  }

  @override
  Future<MeditationSession> createSession(String checkInId) async {
    // The recommendation is intentionally not sent: the server re-derives it,
    // and that is the only authority over which practice runs.
    final Map<String, dynamic> body = await _postJson('/v1/sessions', <
      String,
      dynamic
    >{'check_in_id': checkInId}, expected: 201);
    return MeditationSession.fromJson(body);
  }

  @override
  Future<void> startSession(String sessionId) =>
      _postNoContent('/v1/sessions/$sessionId/start', const <String, dynamic>{});

  @override
  Future<void> submitFeedback(String sessionId, SessionFeedback feedback) =>
      _postNoContent('/v1/sessions/$sessionId/feedback', feedback.toJson());

  @override
  Future<SessionHistoryPage> sessionHistory({
    String? cursor,
    int limit = 20,
  }) async {
    final StringBuffer path = StringBuffer('/v1/sessions/history?limit=$limit');
    if (cursor != null) {
      path.write('&cursor=${Uri.encodeQueryComponent(cursor)}');
    }
    final http.Response response = await _send(path.toString(), method: 'GET');
    if (response.statusCode == 404) {
      return SessionHistoryPage.empty;
    }
    if (response.statusCode != 200) {
      throw ApiException(_describe(response), statusCode: response.statusCode);
    }
    return SessionHistoryPage.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  @override
  Future<void> deleteMyData() async {
    final http.Response response = await _send('/v1/me/data', method: 'DELETE');
    // 404 means there was nothing stored, which is the state the caller wanted.
    if (response.statusCode != 204 && response.statusCode != 404) {
      throw ApiException(_describe(response), statusCode: response.statusCode);
    }
  }

  @override
  Future<Map<String, dynamic>> exportMyData() async {
    final http.Response response = await _send('/v1/me/export', method: 'GET');
    if (response.statusCode != 200) {
      throw ApiException(_describe(response), statusCode: response.statusCode);
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> _postJson(
    String path,
    Map<String, dynamic> payload, {
    required int expected,
  }) async {
    final http.Response response = await _send(path, payload: payload);
    if (response.statusCode != expected) {
      throw ApiException(
        _describe(response),
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<void> _postNoContent(
    String path,
    Map<String, dynamic> payload,
  ) async {
    final http.Response response = await _send(path, payload: payload);
    if (response.statusCode != 204) {
      throw ApiException(
        _describe(response),
        statusCode: response.statusCode,
      );
    }
  }

  Future<http.Response> _send(
    String path, {
    Map<String, dynamic>? payload,
    String method = 'POST',
  }) async {
    final Uri uri = _uri(path);
    final Map<String, String> headers = await _headers();
    final String? body = payload == null ? null : jsonEncode(payload);
    try {
      return await switch (method) {
        'GET' => _client.get(uri, headers: headers),
        'DELETE' => _client.delete(uri, headers: headers),
        _ => _client.post(uri, headers: headers, body: body),
      }.timeout(_timeout);
    } on Exception catch (error) {
      throw ApiException('Could not reach the service: $error');
    }
  }

  String _describe(http.Response response) {
    try {
      final Map<String, dynamic> body =
          jsonDecode(response.body) as Map<String, dynamic>;
      final Object? error = body['error'];
      if (error is Map<String, dynamic> && error['message'] is String) {
        return error['message'] as String;
      }
    } on FormatException {
      // fall through to the generic message
    }
    return 'Request failed (${response.statusCode}).';
  }
}
