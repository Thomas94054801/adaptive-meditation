import '../platform/providers.dart';
import 'api.dart';
import 'durable_store.dart';
import 'guest.dart';
import 'preferences.dart';

/// Guest data deletion as a resumable procedure — Program005 SDD section 9.5.
///
/// Not a chain of unguarded awaits. The state is the existing tombstone plus
/// one `deletion_pending` preference row holding the guest id, so a relaunch
/// after any failure resumes from the first unconfirmed step with the same
/// identity. The identity rotates only when every step has confirmed; until
/// then the old id is what a retry needs, and it stays.
///
/// Every external operation here is idempotent already — DELETE on an absent
/// guest is 404 and counts as done, forgetGuest deletes by table, cancelling
/// a reminder that is not there is a no-op — which is what makes running the
/// procedure twice safe.
enum DeletionStep {
  markPending,
  cancelReminder,
  serverDelete,
  localPurge,
  rotate,
}

class DeletionOutcome {
  const DeletionOutcome({
    required this.complete,
    required this.steps,
    this.failedStep,
    this.message,
  });

  /// Every step confirmed and the identity rotated.
  final bool complete;

  /// The steps that ran, in order, for the caller to show or a test to assert.
  final List<DeletionStep> steps;

  /// The first step that failed, when [complete] is false.
  final DeletionStep? failedStep;

  final String? message;
}

class DeletionProcedure {
  DeletionProcedure({
    required MeditationApi api,
    required DurableStore store,
    required NotificationProvider notifications,
    required GuestIdentity guest,
    DateTime Function()? clock,
  }) : _api = api,
       _store = store,
       _notifications = notifications,
       _guest = guest,
       _clock = clock ?? DateTime.now;

  final MeditationApi _api;
  final DurableStore _store;
  final NotificationProvider _notifications;
  final GuestIdentity _guest;
  final DateTime Function() _clock;

  Preferences get _preferences => Preferences(_store, clock: _clock);

  /// Run after the person confirmed. Uses the current identity.
  Future<DeletionOutcome> run() async {
    final String guestId = await _guest.ensure();
    return _execute(guestId);
  }

  /// At start: finish a deletion a previous run left unconfirmed, if any.
  /// Returns null when nothing was pending.
  Future<DeletionOutcome?> resumeIfPending() async {
    final String? pending = await _preferences.deletionPending();
    if (pending == null) {
      return null;
    }
    return _execute(pending);
  }

  Future<DeletionOutcome> _execute(String guestId) async {
    final List<DeletionStep> steps = <DeletionStep>[];

    // 1. Mark. From here no reminder reconcile and no new local writes for
    //    this guest happen; the reminder intent is off before anything
    //    external is attempted.
    try {
      await _preferences.markDeletionPending(guestId);
      final ReminderPreference intent = await _preferences.reminder();
      if (intent.enabled) {
        await _preferences.setReminder(intent.copyWith(enabled: false));
      }
      steps.add(DeletionStep.markPending);
    } catch (error) {
      return DeletionOutcome(
        complete: false,
        steps: steps,
        failedStep: DeletionStep.markPending,
        message: 'Could not start the deletion on this device: $error',
      );
    }

    // 2. Cancel the OS reminder. No network; a failure is recorded and the
    //    procedure continues, because a data purge must not wait on it.
    bool reminderCancelled = false;
    try {
      await _notifications.cancelReminder();
      reminderCancelled = true;
      steps.add(DeletionStep.cancelReminder);
    } catch (_) {
      // Retried after the purge.
    }

    // 3. Server, with the original identity. 404 is already treated as done
    //    by the API client.
    try {
      await _api.deleteMyData();
      steps.add(DeletionStep.serverDelete);
    } on ApiException catch (error) {
      return DeletionOutcome(
        complete: false,
        steps: steps,
        failedStep: DeletionStep.serverDelete,
        message: error.message,
      );
    } catch (error) {
      return DeletionOutcome(
        complete: false,
        steps: steps,
        failedStep: DeletionStep.serverDelete,
        message: 'Could not reach the server: $error',
      );
    }

    // 4. Local purge: tables, preferences (marker kept), tombstone.
    try {
      await _store.forgetGuest(guestId, nowMs: _clock().millisecondsSinceEpoch);
      steps.add(DeletionStep.localPurge);
    } catch (error) {
      return DeletionOutcome(
        complete: false,
        steps: steps,
        failedStep: DeletionStep.localPurge,
        message: 'Deleted on the server; could not clear this device: $error',
      );
    }

    // 2 again, if it failed the first time. Only then is everything
    //    confirmed.
    if (!reminderCancelled) {
      try {
        await _notifications.cancelReminder();
        steps.add(DeletionStep.cancelReminder);
      } catch (error) {
        return DeletionOutcome(
          complete: false,
          steps: steps,
          failedStep: DeletionStep.cancelReminder,
          message: 'Data deleted; the reminder could not be cancelled: $error',
        );
      }
    }

    // 5. Rotate, then clear the marker. Rotating first: if clearing the
    //    marker fails, the next start re-runs the procedure against an id
    //    that has no data anywhere, which is harmless; the reverse order
    //    could leave a live id with a cleared marker.
    try {
      await _guest.rotate();
      await _preferences.clearDeletionPending();
      steps.add(DeletionStep.rotate);
    } catch (error) {
      return DeletionOutcome(
        complete: false,
        steps: steps,
        failedStep: DeletionStep.rotate,
        message: 'Data deleted; could not start a fresh identity: $error',
      );
    }
    return DeletionOutcome(complete: true, steps: steps);
  }
}
