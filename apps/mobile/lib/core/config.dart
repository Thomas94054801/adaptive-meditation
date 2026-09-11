/// Build-time configuration.
///
/// Supplied with `--dart-define`, never committed. There is no API key here:
/// the backend needs no credential from the client in Program001.
class AppConfig {
  const AppConfig({required this.apiBaseUrl});

  /// Defaults to a local backend so a developer build runs with no flags.
  factory AppConfig.fromEnvironment() => const AppConfig(
    apiBaseUrl: String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: 'http://localhost:8000',
    ),
  );

  final String apiBaseUrl;
}
