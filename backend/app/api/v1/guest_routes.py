"""Guest-owned data: history, export and deletion.

Every route here acts on the caller's own ``X-Guest-Id`` and nothing else. There
is no way to name another guest's id and read it back, because no route takes an
id as a parameter.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import DbSessionDep, RequiredGuestDep
from app.api.v1.schemas import (
    ErrorResponse,
    GuestExportResponse,
    SessionHistoryPage,
    SessionSummary,
)
from app.persistence.repositories import CheckInRepository, GuestRepository, SessionRepository

router = APIRouter(prefix="/v1", tags=["guest"])

HISTORY_PAGE_DEFAULT = 20
HISTORY_PAGE_MAX = 100

GUEST_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Guest identity required"},
    404: {"model": ErrorResponse, "description": "Unknown guest"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}


def _as_str(value: object) -> str:
    """JSON columns are typed as object; narrow without trusting the content."""
    return value if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def encode_cursor(created_at: datetime, session_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{session_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode()
        timestamp, _, session_id = raw.partition("|")
        return datetime.fromisoformat(timestamp), uuid.UUID(session_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_cursor", "message": "The cursor is not valid."},
        ) from None


@router.get(
    "/sessions/history",
    operation_id="listSessionHistory",
    response_model=SessionHistoryPage,
    responses={k: GUEST_ERRORS[k] for k in (401, 422)},
    summary="This guest's past sessions, newest first",
)
def list_session_history(
    guest_id: RequiredGuestDep,
    db: DbSessionDep,
    limit: int = Query(HISTORY_PAGE_DEFAULT, ge=1, le=HISTORY_PAGE_MAX),
    cursor: str | None = Query(None),
) -> SessionHistoryPage:
    sessions = SessionRepository(db)
    before = decode_cursor(cursor) if cursor else None
    # One extra row tells us whether another page exists without a count query.
    rows = sessions.history(guest_id, limit=limit + 1, before=before)
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        SessionSummary(
            id=row.id,
            status=row.status,
            created_at=row.created_at,
            completed_at=row.completed_at,
            practice_id=_as_str(row.recommendation.get("practice_id")),
            public_title=_as_str(row.plan.get("public_title")),
            duration_minutes=_as_int(row.recommendation.get("duration_minutes")),
            rule_set_version=row.rule_set_version,
            outcome_score=row.feedback.outcome_score if row.feedback else None,
        )
        for row in page
    ]
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
    return SessionHistoryPage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/me/export",
    operation_id="exportGuestData",
    response_model=GuestExportResponse,
    responses={k: GUEST_ERRORS[k] for k in (401, 404)},
    summary="Everything stored for this guest",
)
def export_guest_data(guest_id: RequiredGuestDep, db: DbSessionDep) -> GuestExportResponse:
    guests = GuestRepository(db)
    if not guests.exists(guest_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "guest_not_found", "message": "No data is stored for this guest."},
        )

    check_ins = CheckInRepository(db).for_guest(guest_id)
    sessions_repo = SessionRepository(db)
    # Unbounded by design: an export is the whole record or it is not an export.
    # Guest volume is bounded by one person's own sessions.
    session_rows = sessions_repo.history(guest_id, limit=100_000)

    return GuestExportResponse(
        guest_id=guest_id,
        check_ins=[
            {
                "id": str(row.id),
                "created_at": row.created_at.isoformat(),
                "goal": row.goal,
                "stress": row.stress,
                "energy": row.energy,
                "mental_activity": row.mental_activity,
                "sleepiness": row.sleepiness,
                "available_minutes": row.available_minutes,
                "experience_level": row.experience_level,
            }
            for row in check_ins
        ],
        recommendations=[
            {
                "session_id": str(row.id),
                "created_at": row.created_at.isoformat(),
                **row.recommendation,
            }
            for row in session_rows
        ],
        sessions=[
            {
                "id": str(row.id),
                "check_in_id": str(row.check_in_id),
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "protocol_id": row.protocol_id,
                "plan": row.plan,
            }
            for row in session_rows
        ],
        feedback=[
            {
                "session_id": str(row.id),
                "before_score": row.feedback.before_score,
                "after_score": row.feedback.after_score,
                "helpfulness": row.feedback.helpfulness,
                "completed": row.feedback.completed,
                "notes": row.feedback.notes,
                "stress_after": row.feedback.stress_after,
                "energy_after": row.feedback.energy_after,
                "mental_activity_after": row.feedback.mental_activity_after,
                "sleepiness_after": row.feedback.sleepiness_after,
                "completion_ratio": row.feedback.completion_ratio,
                "primary_measure": row.feedback.primary_measure,
                "primary_delta": row.feedback.primary_delta,
                "secondary_measure": row.feedback.secondary_measure,
                "secondary_delta": row.feedback.secondary_delta,
                # product optimization metric only
                "outcome_score": row.feedback.outcome_score,
            }
            for row in session_rows
            if row.feedback is not None
        ],
        experiment_assignments=[
            {
                "experiment_id": row.experiment_id,
                "variant": row.variant,
                "assignment_key": row.assignment_key,
                "assigned_at": row.assigned_at.isoformat(),
            }
            for row in guests.assignments(guest_id)
        ],
        # Exposures are exported separately from assignments, for the same
        # reason they are stored separately: they are different facts.
        experiment_exposures=[
            {
                "experiment_id": row.experiment_id,
                "variant": row.variant,
                "context": row.context,
                "exposed_at": row.exposed_at.isoformat(),
            }
            for row in guests.exposures(guest_id)
        ],
    )


@router.delete(
    "/me/data",
    operation_id="deleteGuestData",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={k: GUEST_ERRORS[k] for k in (401, 404)},
    summary="Delete everything stored for this guest",
)
def delete_guest_data(guest_id: RequiredGuestDep, db: DbSessionDep) -> Response:
    """Deletes the guest row; the database cascades to everything else.

    One statement rather than a list of tables, so a table added later cannot be
    forgotten here.
    """
    if not GuestRepository(db).delete(guest_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "guest_not_found", "message": "No data is stored for this guest."},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
