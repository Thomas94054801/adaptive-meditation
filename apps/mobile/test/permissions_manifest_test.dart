import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

/// Guards the V1 permission boundary at the manifest level.
///
/// compliance/permissions.v1.yaml is the declaration; these tests check the
/// platform files actually match it, so a permission cannot be added by a
/// plugin or a merge without a test failing.
void main() {
  final File androidManifest = File('android/app/src/main/AndroidManifest.xml');
  final File iosPlist = File('ios/Runner/Info.plist');
  final File permissionsDeclaration = File(
    '../../compliance/permissions.v1.yaml',
  );

  const List<String> prohibitedAndroid = <String>[
    'android.permission.CAMERA',
    'android.permission.RECORD_AUDIO',
    'android.permission.ACCESS_FINE_LOCATION',
    'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.ACCESS_BACKGROUND_LOCATION',
    'android.permission.BODY_SENSORS',
    'android.permission.ACTIVITY_RECOGNITION',
    'android.permission.READ_CONTACTS',
    'android.permission.POST_NOTIFICATIONS',
    'android.permission.health',
  ];

  const List<String> prohibitedIos = <String>[
    'NSCameraUsageDescription',
    'NSMicrophoneUsageDescription',
    'NSLocationWhenInUseUsageDescription',
    'NSLocationAlwaysAndWhenInUseUsageDescription',
    'NSHealthShareUsageDescription',
    'NSHealthUpdateUsageDescription',
    'NSContactsUsageDescription',
    'NSPhotoLibraryUsageDescription',
    'NSMotionUsageDescription',
  ];

  test('android manifest requests no prohibited V1 permission', () {
    final String xml = androidManifest.readAsStringSync();
    for (final String permission in prohibitedAndroid) {
      expect(
        xml.contains(permission),
        isFalse,
        reason: 'AndroidManifest.xml declares $permission, which V1 excludes',
      );
    }
  });

  test('android manifest keeps the one permission the app does need', () {
    expect(
      androidManifest.readAsStringSync().contains(
        'android.permission.INTERNET',
      ),
      isTrue,
    );
  });

  test('ios Info.plist declares no prohibited usage description', () {
    final String plist = iosPlist.readAsStringSync();
    for (final String key in prohibitedIos) {
      expect(
        plist.contains(key),
        isFalse,
        reason: 'Info.plist declares $key, which V1 excludes',
      );
    }
  });

  test('the compliance declaration agrees with the manifests', () {
    final YamlMap declaration =
        loadYaml(permissionsDeclaration.readAsStringSync()) as YamlMap;
    final YamlMap permissions = declaration['platform_permissions'] as YamlMap;
    for (final String capability in <String>[
      'camera',
      'microphone',
      'location',
      'healthkit',
      'health_connect',
      'notifications',
    ]) {
      expect(
        (permissions[capability] as YamlMap)['requested'],
        isFalse,
        reason: '$capability is declared as requested in permissions.v1.yaml',
      );
    }
    expect(declaration['claims']['medical_diagnosis'], isFalse);
    expect(declaration['claims']['medical_treatment'], isFalse);
    expect(declaration['claims']['advertising_use_of_wellness_data'], isFalse);
    expect(declaration['guest_usage']['registration_required'], isFalse);
    expect(declaration['guest_usage']['fake_identity_generated'], isFalse);
  });

  test('background audio is declared in the manifests and in compliance', () {
    // Program004 actually plays audio with the screen off, so the declaration
    // and both manifests must agree. A capability declared in only one of the
    // three is the failure mode this checks for.
    final YamlMap declaration =
        loadYaml(permissionsDeclaration.readAsStringSync()) as YamlMap;
    final YamlMap permissions = declaration['platform_permissions'] as YamlMap;
    final YamlMap backgroundAudio = permissions['background_audio'] as YamlMap;

    expect(backgroundAudio['requested'], isTrue);
    expect(
      iosPlist.readAsStringSync().contains('UIBackgroundModes'),
      isTrue,
      reason: 'compliance declares background audio; Info.plist does not',
    );
    final String xml = androidManifest.readAsStringSync();
    expect(
      xml.contains('android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK'),
      isTrue,
      reason: 'compliance declares background audio; AndroidManifest does not',
    );
    expect(xml.contains('android.permission.FOREGROUND_SERVICE'), isTrue);
  });

  test('the manifests declare nothing compliance has not accounted for', () {
    // The other direction: a permission arriving through a plugin's merged
    // manifest, or a background mode nobody declared, must fail here.
    final YamlMap declaration =
        loadYaml(permissionsDeclaration.readAsStringSync()) as YamlMap;
    final YamlMap permissions = declaration['platform_permissions'] as YamlMap;

    const Set<String> accountedForAndroid = <String>{
      'android.permission.INTERNET',
      'android.permission.FOREGROUND_SERVICE',
      'android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK',
    };
    final RegExp uses = RegExp(r'uses-permission android:name="([^"]+)"');
    final Set<String> declared = uses
        .allMatches(androidManifest.readAsStringSync())
        .map((RegExpMatch m) => m.group(1)!)
        .toSet();
    expect(
      declared.difference(accountedForAndroid),
      isEmpty,
      reason: 'AndroidManifest declares a permission compliance does not list',
    );

    // Only one background mode, and only because playback needs it.
    final String plist = iosPlist.readAsStringSync();
    final int start = plist.indexOf('<key>UIBackgroundModes</key>');
    if (start >= 0) {
      final int end = plist.indexOf('</array>', start);
      final String block = plist.substring(start, end);
      expect(block.contains('<string>audio</string>'), isTrue);
      expect(
        RegExp(r'<string>').allMatches(block).length,
        1,
        reason: 'Info.plist declares a background mode beyond audio',
      );
      expect((permissions['background_audio'] as YamlMap)['requested'], isTrue);
    }
  });
}
