"""Data access for the vertical slice.

Every query is expressed through the ORM with bound parameters; no SQL string is
assembled from request data.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.domain.audio.render import RenderResult
from app.domain.experiment.assignment import Assignment
from app.domain.outcome.models import SessionOutcome
from app.domain.recommendation.engine import Recommendation
from app.domain.recommendation.scoring import RuleOutcome
from app.domain.session.planner import SessionPlan
from app.domain.state.models import CheckIn as CheckInModel
from app.domain.timeline.definition import SessionDefinition
from app.domain.timeline.resolution import ResolvedTimeline
from app.persistence import models


def utcnow() -> datetime:
    return datetime.now(UTC)


class GuestRepository:
    """Guest identities. A guest row is created on first sight, never demanded."""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def touch(self, guest_id: uuid.UUID) -> models.GuestProfile:
        row = self._session.get(models.GuestProfile, guest_id)
        if row is None:
            row = models.GuestProfile(id=guest_id, created_at=utcnow(), last_seen_at=utcnow())
            self._session.add(row)
        else:
            row.last_seen_at = utcnow()
        self._session.flush()
        return row

    def exists(self, guest_id: uuid.UUID) -> bool:
        return self._session.get(models.GuestProfile, guest_id) is not None

    def delete(self, guest_id: uuid.UUID) -> bool:
        """Delete the guest and, by cascade, everything hanging off it."""
        row = self._session.get(models.GuestProfile, guest_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def assignment(
        self, guest_id: uuid.UUID, assignment: Assignment
    ) -> models.ExperimentAssignment:
        """Record a deterministic assignment. Idempotent by construction.

        Steady state is one SELECT. The guest profile is created here, on the
        first assignment only, rather than by an unconditional touch on every
        call - three round trips per recommendation is what pushed this
        endpoint's p95 from 1.07 ms to 2.9 ms.
        """
        stmt = select(models.ExperimentAssignment).where(
            models.ExperimentAssignment.guest_id == guest_id,
            models.ExperimentAssignment.experiment_id == assignment.experiment_id,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is not None:
            return row

        # The profile must exist for the foreign key. touch() flushes it before
        # the assignment insert is added, so the ordering is safe.
        self.touch(guest_id)
        row = models.ExperimentAssignment(
            id=uuid.uuid4(),
            guest_id=guest_id,
            experiment_id=assignment.experiment_id,
            variant=assignment.variant,
            assignment_key=assignment.assignment_key,
            assigned_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def record_exposure(
        self, *, guest_id: uuid.UUID, experiment_id: str, variant: str, context: str
    ) -> tuple[models.ExperimentExposure, bool]:
        """Record that a variant was actually shown. Returns (row, created).

        Idempotent per (guest, experiment, context): re-opening the same screen
        is the same exposure, not a new one.
        """
        stmt = select(models.ExperimentExposure).where(
            models.ExperimentExposure.guest_id == guest_id,
            models.ExperimentExposure.experiment_id == experiment_id,
            models.ExperimentExposure.context == context,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is not None:
            return row, False
        row = models.ExperimentExposure(
            id=uuid.uuid4(),
            guest_id=guest_id,
            experiment_id=experiment_id,
            variant=variant,
            context=context,
            exposed_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row, True

    def exposures(self, guest_id: uuid.UUID) -> list[models.ExperimentExposure]:
        stmt = select(models.ExperimentExposure).where(
            models.ExperimentExposure.guest_id == guest_id
        )
        return list(self._session.execute(stmt).scalars())

    def assignments(self, guest_id: uuid.UUID) -> list[models.ExperimentAssignment]:
        stmt = select(models.ExperimentAssignment).where(
            models.ExperimentAssignment.guest_id == guest_id
        )
        return list(self._session.execute(stmt).scalars())


class CheckInRepository:
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def create(
        self,
        check_in: CheckInModel,
        *,
        user_id: uuid.UUID | None = None,
        guest_id: uuid.UUID | None = None,
    ) -> models.CheckIn:
        row = models.CheckIn(
            id=uuid.uuid4(),
            user_id=user_id,
            guest_id=guest_id,
            goal=check_in.goal.value,
            stress=check_in.stress,
            energy=check_in.energy,
            mental_activity=check_in.mental_activity,
            sleepiness=check_in.sleepiness,
            available_minutes=check_in.available_minutes,
            experience_level=check_in.experience_level.value,
            created_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, check_in_id: uuid.UUID) -> models.CheckIn | None:
        return self._session.get(models.CheckIn, check_in_id)

    def for_guest(self, guest_id: uuid.UUID) -> list[models.CheckIn]:
        stmt = (
            select(models.CheckIn)
            .where(models.CheckIn.guest_id == guest_id)
            .order_by(models.CheckIn.created_at.desc(), models.CheckIn.id.desc())
        )
        return list(self._session.execute(stmt).scalars())

    @staticmethod
    def to_domain(row: models.CheckIn) -> CheckInModel:
        return CheckInModel.model_validate(
            {
                "goal": row.goal,
                "stress": row.stress,
                "energy": row.energy,
                "mental_activity": row.mental_activity,
                "sleepiness": row.sleepiness,
                "available_minutes": row.available_minutes,
                "experience_level": row.experience_level,
            }
        )


class SessionRepository:
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def create(
        self,
        *,
        check_in_id: uuid.UUID,
        recommendation: Recommendation,
        plan: SessionPlan,
        user_id: uuid.UUID | None = None,
        guest_id: uuid.UUID | None = None,
        outcome: RuleOutcome | None = None,
        plan_v2: dict[str, object] | None = None,
        plan_hash: str | None = None,
        definition_id: str | None = None,
    ) -> models.Session:
        row = models.Session(
            id=uuid.uuid4(),
            user_id=user_id,
            guest_id=guest_id,
            check_in_id=check_in_id,
            recommendation=recommendation.model_dump(mode="json"),
            protocol_id=plan.protocol_id,
            protocol_version=plan.protocol_version,
            plan=plan.as_dict(),
            status="created",
            created_at=utcnow(),
            engine_version=recommendation.engine_version,
            rule_set_version=recommendation.rule_set_version,
            state_fingerprint=recommendation.state_fingerprint or None,
            plan_v2=plan_v2,
            plan_hash=plan_hash,
            definition_id=definition_id,
            run_state="created",
            elapsed_ms=0,
            command_sequence=0,
        )
        self._session.add(row)
        self._session.flush()
        if outcome is not None:
            # Bounded: one row per practice, seven in v2.
            for rank, candidate in enumerate(outcome.candidates):
                self._session.add(
                    models.RecommendationCandidate(
                        id=uuid.uuid4(),
                        session_id=row.id,
                        practice_id=candidate.practice_id.value,
                        rank=rank,
                        score=candidate.score,
                        reason_codes=[code.value for code in candidate.reason_codes],
                    )
                )
            self._session.flush()
        return row

    def history(
        self,
        guest_id: uuid.UUID,
        *,
        limit: int,
        before: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[models.Session]:
        """One page of a guest's sessions, newest first.

        Keyset pagination on (created_at, id): stable when rows are inserted
        during paging, which OFFSET is not.
        """
        stmt = select(models.Session).where(models.Session.guest_id == guest_id)
        if before is not None:
            created_at, session_id = before
            stmt = stmt.where(
                sa.tuple_(models.Session.created_at, models.Session.id) < (created_at, session_id)
            )
        stmt = stmt.order_by(models.Session.created_at.desc(), models.Session.id.desc()).limit(
            limit
        )
        return list(self._session.execute(stmt).scalars())

    def get(self, session_id: uuid.UUID) -> models.Session | None:
        return self._session.get(models.Session, session_id)

    def mark_started(self, row: models.Session) -> models.Session:
        if row.status == "created":
            row.status = "started"
            row.started_at = utcnow()
            self._session.flush()
        return row

    def finish(self, row: models.Session, *, completed: bool) -> models.Session:
        row.status = "completed" if completed else "abandoned"
        row.completed_at = utcnow()
        if row.started_at is None:
            row.started_at = row.completed_at
        self._session.flush()
        return row

    def get_feedback(self, session_id: uuid.UUID) -> models.SessionFeedback | None:
        stmt = select(models.SessionFeedback).where(models.SessionFeedback.session_id == session_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def upsert_feedback(
        self,
        *,
        session_id: uuid.UUID,
        before_score: int | None,
        after_score: int,
        helpfulness: int,
        completed: bool,
        notes: str | None,
        outcome: SessionOutcome | None = None,
    ) -> models.SessionFeedback:
        row = self.get_feedback(session_id)
        if row is None:
            row = models.SessionFeedback(
                id=uuid.uuid4(), session_id=session_id, created_at=utcnow()
            )
            self._session.add(row)
        row.before_score = before_score
        row.after_score = after_score
        row.helpfulness = helpfulness
        row.completed = completed
        row.notes = notes
        if outcome is not None:
            # Raw after-state first; the derived fields are recomputable from it.
            row.stress_after = outcome.after.stress
            row.energy_after = outcome.after.energy
            row.mental_activity_after = outcome.after.mental_activity
            row.sleepiness_after = outcome.after.sleepiness
            row.completion_ratio = outcome.completion_ratio
            row.primary_measure = outcome.primary_measure.value
            row.primary_delta = outcome.primary_delta
            row.secondary_measure = (
                outcome.secondary_measure.value if outcome.secondary_measure else None
            )
            row.secondary_delta = outcome.secondary_delta
            row.outcome_score = outcome.outcome_score
        self._session.flush()
        return row

    def candidates(self, session_id: uuid.UUID) -> list[models.RecommendationCandidate]:
        stmt = (
            select(models.RecommendationCandidate)
            .where(models.RecommendationCandidate.session_id == session_id)
            .order_by(models.RecommendationCandidate.rank)
        )
        return list(self._session.execute(stmt).scalars())


class SessionDefinitionRepository:
    """Frozen guidance content.

    Write-once by construction: a definition is addressed by the hash of its own
    content, so "updating" one is a contradiction - different content is a
    different id.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def ensure(self, definition: SessionDefinition) -> models.SessionDefinitionRow:
        existing = self._session.get(models.SessionDefinitionRow, definition.definition_id)
        if existing is not None:
            return existing
        row = models.SessionDefinitionRow(
            id=definition.definition_id,
            practice_id=definition.practice_id,
            protocol_id=definition.protocol_id,
            locale=definition.locale,
            source=definition.source.value,
            version=definition.version,
            content=definition.as_dict(),
            created_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, definition_id: str) -> SessionDefinition | None:
        row = self._session.get(models.SessionDefinitionRow, definition_id)
        if row is None:
            return None
        return SessionDefinition.from_dict(dict(row.content))


class SessionResolutionRepository:
    """Resolutions, one row per revision.

    Append-only by revision: a repaired resolution is a new row, so the prefix
    a user already heard stays explainable. There is deliberately no update.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def latest(self, session_id: uuid.UUID) -> models.SessionResolution | None:
        stmt = (
            select(models.SessionResolution)
            .where(models.SessionResolution.session_id == session_id)
            .order_by(models.SessionResolution.revision.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_revision(self, session_id: uuid.UUID, revision: int) -> models.SessionResolution | None:
        stmt = select(models.SessionResolution).where(
            models.SessionResolution.session_id == session_id,
            models.SessionResolution.revision == revision,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def record(
        self,
        *,
        session_id: uuid.UUID,
        resolution: ResolvedTimeline,
        server_validated: bool,
    ) -> tuple[models.SessionResolution, bool]:
        """Store a resolution. Returns (row, created).

        Idempotent on (session, revision): a client retrying after a dropped
        response finds the existing row. A retry carrying *different* content
        for the same revision is a conflict, not a duplicate, and the caller
        raises rather than silently keeping either version.
        """
        existing = self.get_revision(session_id, resolution.revision)
        if existing is not None:
            if existing.resolution_hash != resolution.resolution_hash:
                raise ResolutionRevisionConflict(
                    f"revision {resolution.revision} already exists with different content"
                )
            return existing, False

        row = models.SessionResolution(
            id=uuid.uuid4(),
            session_id=session_id,
            revision=resolution.revision,
            resolution_hash=resolution.resolution_hash,
            plan_hash=resolution.plan_hash,
            canonicalization_version=resolution.canonicalization_version,
            timing_policy_version=resolution.timing_policy_version,
            measurement_source=resolution.measurement_source.value,
            audio_mode=resolution.audio_mode,
            total_ms=resolution.total_ms,
            extended_by_ms=resolution.extended_by_ms,
            absorbed_ms=resolution.absorbed_ms,
            outcome=resolution.outcome,
            content=resolution.as_dict(),
            server_validated=server_validated,
            created_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row, True


class SequenceTaken(Exception):
    """Another record already holds that sequence number."""


class ResolutionRevisionConflict(Exception):
    """The same revision arrived twice with different content."""


class AudioRenderRepository:
    """Measured renders, addressed by content.

    Write-once like the definitions: a render_key already present describes the
    same bytes by construction, so recording one again is a no-op rather than an
    update. Nothing here takes a guest id, because nothing here is about a guest.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def get(self, render_key: str) -> RenderResult | None:
        row = self._session.get(models.AudioRender, render_key)
        if row is None:
            return None
        return RenderResult(
            render_key=row.render_key,
            duration_ms=row.duration_ms,
            content_sha256=row.content_sha256,
            uri=row.uri,
            provider_id=row.provider_id,
            provider_version=row.provider_version,
            byte_size=row.byte_size,
        )

    def record(
        self,
        result: RenderResult,
        *,
        locale: str,
        voice_id: str,
        style: str,
        render_version: str = "1",
    ) -> models.AudioRender:
        existing = self._session.get(models.AudioRender, result.render_key)
        if existing is not None:
            return existing
        row = models.AudioRender(
            render_key=result.render_key,
            locale=locale,
            voice_id=voice_id,
            style=style,
            provider_id=result.provider_id,
            provider_version=result.provider_version,
            render_version=render_version,
            duration_ms=result.duration_ms,
            content_sha256=result.content_sha256,
            byte_size=result.byte_size,
            uri=result.uri,
            created_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def measured_durations(self, render_keys: list[str]) -> dict[str, int]:
        """Measured durations for keys already rendered — SDD section 9.3.

        The planner reads these and estimates only when they are missing, so
        planning accuracy improves as the corpus warms.
        """
        if not render_keys:
            return {}
        stmt = select(models.AudioRender.render_key, models.AudioRender.duration_ms).where(
            models.AudioRender.render_key.in_(render_keys)
        )
        return dict(self._session.execute(stmt).all())  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EventDraft:
    """One event a client is asking to append."""

    sequence: int
    event_type: str
    segment_id: str | None = None
    elapsed_ms: int = 0
    command_id: str | None = None
    detail: dict[str, object] | None = None


class SessionEventRepository:
    """Append-only playback journal.

    Only ``append`` and ``read`` exist. There is deliberately no update and no
    delete: a log that can be rewritten is not evidence, and the only way rows
    leave is the guest-deletion cascade.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def append(
        self,
        *,
        session_id: uuid.UUID,
        sequence: int,
        event_type: str,
        segment_id: str | None = None,
        elapsed_ms: int = 0,
        command_id: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> tuple[models.SessionEvent, bool]:
        """Append one event. Returns (row, created).

        Idempotent on (session, sequence): a retried request finds the existing
        row rather than duplicating it, which is what makes the client free to
        retry after a dropped connection.
        """
        stmt = select(models.SessionEvent).where(
            models.SessionEvent.session_id == session_id,
            models.SessionEvent.sequence == sequence,
        )
        existing = self._session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return existing, False

        row = models.SessionEvent(
            id=uuid.uuid4(),
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            segment_id=segment_id,
            elapsed_ms=max(0, elapsed_ms),
            command_id=command_id,
            detail=detail,
            occurred_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row, True

    def append_many(self, session_id: uuid.UUID, events: Sequence[EventDraft]) -> tuple[int, int]:
        """Append a batch, returning (accepted, duplicates).

        Two queries regardless of batch size - one to read the sequences already
        present, one to insert the rest - because the budget is two per batch
        and a select-then-insert per event turns a 200-event batch into 400
        round trips.
        """
        if not events:
            return 0, 0

        wanted = {event.sequence for event in events}
        taken_stmt = select(models.SessionEvent.sequence).where(
            models.SessionEvent.session_id == session_id,
            models.SessionEvent.sequence.in_(wanted),
        )
        taken = set(self._session.execute(taken_stmt).scalars())

        now = utcnow()
        rows: list[models.SessionEvent] = []
        # Within one batch a repeated sequence is itself a duplicate; without
        # this the unique constraint would reject the whole insert.
        seen: set[int] = set()
        for event in events:
            if event.sequence in taken or event.sequence in seen:
                continue
            seen.add(event.sequence)
            rows.append(
                models.SessionEvent(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    segment_id=event.segment_id,
                    elapsed_ms=max(0, event.elapsed_ms),
                    command_id=event.command_id,
                    detail=event.detail,
                    occurred_at=now,
                )
            )

        if rows:
            self._session.add_all(rows)
            self._session.flush()
        return len(rows), len(events) - len(rows)

    def command_record(self, session_id: uuid.UUID, command_id: str) -> models.SessionEvent | None:
        """The journal row a command already wrote, if any."""
        stmt = select(models.SessionEvent).where(
            models.SessionEvent.session_id == session_id,
            models.SessionEvent.command_id == command_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def append_command(
        self,
        *,
        session_id: uuid.UUID,
        sequence: int,
        event_type: str,
        command_id: str,
        payload_digest: str,
        segment_id: str | None = None,
        elapsed_ms: int = 0,
        detail: dict[str, object] | None = None,
    ) -> tuple[models.SessionEvent, bool]:
        """Record a command's journal entry, atomically.

        Relies on the ``(session_id, command_id)`` unique constraint rather
        than a preceding SELECT. Two concurrent retries of the same command
        both pass a select-then-insert check and then both insert; only a
        constraint stops that, and a savepoint is what lets this recover from
        the loser's IntegrityError without losing the surrounding transaction.
        """
        savepoint = self._session.begin_nested()
        row = models.SessionEvent(
            id=uuid.uuid4(),
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            segment_id=segment_id,
            elapsed_ms=max(0, elapsed_ms),
            command_id=command_id,
            payload_digest=payload_digest,
            detail=detail,
            occurred_at=utcnow(),
        )
        self._session.add(row)
        try:
            savepoint.commit()
        except sa.exc.IntegrityError:
            savepoint.rollback()
            existing = self.command_record(session_id, command_id)
            if existing is None:
                # The conflict was on (session, sequence): something else
                # already holds that number. A typed error, because the caller
                # treats it completely differently from a command retry.
                raise SequenceTaken(
                    f"sequence {sequence} is already recorded for this session"
                ) from None
            return existing, False
        return row, True

    def command_already_applied(self, session_id: uuid.UUID, command_id: str) -> bool:
        """Whether this command_id is already in the journal.

        SDD section 5.4: replaying a command_id returns the same result without
        re-applying it. The sequence rule catches an identical retry; this
        catches a client that retried the same command under a new sequence,
        which is the case that would otherwise double-apply.
        """
        stmt = (
            select(models.SessionEvent.id)
            .where(
                models.SessionEvent.session_id == session_id,
                models.SessionEvent.command_id == command_id,
            )
            .limit(1)
        )
        return self._session.execute(stmt).first() is not None

    def read(self, session_id: uuid.UUID) -> list[models.SessionEvent]:
        stmt = (
            select(models.SessionEvent)
            .where(models.SessionEvent.session_id == session_id)
            .order_by(models.SessionEvent.sequence)
        )
        return list(self._session.execute(stmt).scalars())

    def highest_sequence(self, session_id: uuid.UUID) -> int:
        stmt = select(sa.func.max(models.SessionEvent.sequence)).where(
            models.SessionEvent.session_id == session_id
        )
        return int(self._session.execute(stmt).scalar() or -1)

    def for_guest(self, guest_id: uuid.UUID) -> list[models.SessionEvent]:
        """Every event for one guest, for the export.

        Bounded by that one person's own practice: roughly twenty rows per
        session, so a heavy user with a thousand sessions is about twenty
        thousand small rows. Unbounded by design, like the rest of the export -
        an export that silently stops early is not an export.
        """
        session_ids = select(models.Session.id).where(models.Session.guest_id == guest_id)
        stmt = (
            select(models.SessionEvent)
            .where(models.SessionEvent.session_id.in_(session_ids))
            .order_by(models.SessionEvent.session_id, models.SessionEvent.sequence)
        )
        return list(self._session.execute(stmt).scalars())
