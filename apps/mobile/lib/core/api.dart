import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';
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
}

class HttpMeditationApi implements MeditationApi {
  HttpMeditationApi({required AppConfig config, http.Client? client})
    : _config = config,
      _client = client ?? http.Client();

  final AppConfig _config;
  final http.Client _client;
  static const Duration _timeout = Duration(seconds: 15);

  Uri _uri(String path) => Uri.parse('${_config.apiBaseUrl}$path');

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

  Future<Map<String, dynamic>> _postJson(
    String path,
    Map<String, dynamic> payload, {
    required int expected,
  }) async {
    final http.Response response = await _send(path, payload);
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
    final http.Response response = await _send(path, payload);
    if (response.statusCode != 204) {
      throw ApiException(
        _describe(response),
        statusCode: response.statusCode,
      );
    }
  }

  Future<http.Response> _send(String path, Map<String, dynamic> payload) async {
    try {
      return await _client
          .post(
            _uri(path),
            headers: const <String, String>{
              'content-type': 'application/json',
              'accept': 'application/json',
            },
            body: jsonEncode(payload),
          )
          .timeout(_timeout);
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
