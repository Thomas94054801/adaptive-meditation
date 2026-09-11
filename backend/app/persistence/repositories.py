"""Data access for the vertical slice.

Every query is expressed through the ORM with bound parameters; no SQL string is
assembled from request data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.domain.experiment.assignment import Assignment
from app.domain.outcome.models import SessionOutcome
from app.domain.recommendation.engine import Recommendation
from app.domain.recommendation.scoring import RuleOutcome
from app.domain.session.planner import SessionPlan
from app.domain.state.models import CheckIn as CheckInModel
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
        """Record a deterministic assignment. Idempotent by construction."""
        stmt = select(models.ExperimentAssignment).where(
            models.ExperimentAssignment.guest_id == guest_id,
            models.ExperimentAssignment.experiment_id == assignment.experiment_id,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
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
