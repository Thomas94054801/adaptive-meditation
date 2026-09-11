import 'package:adaptive_meditation/app/app_scope.dart';
import 'package:adaptive_meditation/core/api.dart';
import 'package:adaptive_meditation/core/guest.dart';
import 'package:adaptive_meditation/core/models.dart';
import 'package:adaptive_meditation/features/history/history_store.dart';
import 'package:adaptive_meditation/platform/providers.dart';
import 'package:adaptive_meditation/platform/secure_identity_store.dart';
import 'package:flutter/material.dart';

const CheckIn sampleCheckIn = CheckIn(
  goal: Goal.overthinking,
  stress: 8,
  energy: 5,
  mentalActivity: 9,
  sleepiness: 2,
  availableMinutes: 10,
  experienceLevel: ExperienceLevel.beginner,
);

/// Wraps a screen in the scope it expects, with in-memory everything.
Widget wrap(
  Widget child, {
  required MeditationApi api,
  SessionHistoryStore? history,
  PlatformAdapters? adapters,
  SecureIdentityStore? store,
}) {
  final SecureIdentityStore identityStore = store ?? InMemoryIdentityStore();
  return AppScope(
    api: api,
    guest: GuestIdentity(identityStore),
    history: history ?? SessionHistoryStore(),
    adapters:
        adapters ??
        PlatformAdapters(storage: SecureStorageProviderAdapter(identityStore)),
    child: MaterialApp(home: child),
  );
}
