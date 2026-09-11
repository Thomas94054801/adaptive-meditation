"""Data access for the vertical slice.

Every query is expressed through the ORM with bound parameters; no SQL string is
assembled from request data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.domain.recommendation.engine import Recommendation
from app.domain.session.planner import SessionPlan
from app.domain.state.models import CheckIn as CheckInModel
from app.persistence import models


def utcnow() -> datetime:
    return datetime.now(UTC)


class CheckInRepository:
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def create(self, check_in: CheckInModel, *, user_id: uuid.UUID | None = None) -> models.CheckIn:
        row = models.CheckIn(
            id=uuid.uuid4(),
            user_id=user_id,
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
    ) -> models.Session:
        row = models.Session(
            id=uuid.uuid4(),
            user_id=user_id,
            check_in_id=check_in_id,
            recommendation=recommendation.model_dump(mode="json"),
            protocol_id=plan.protocol_id,
            protocol_version=plan.protocol_version,
            plan=plan.as_dict(),
            status="created",
            created_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row

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
        self._session.flush()
        return row
