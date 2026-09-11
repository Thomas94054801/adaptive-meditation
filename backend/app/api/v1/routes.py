"""v1 endpoints for the check-in -> recommendation -> session -> feedback slice."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import (
    CatalogDep,
    DatabaseDep,
    DbSessionDep,
    EngineDep,
    OptionalGuestDep,
    RequiredGuestDep,
)
from app.api.v1.schemas import (
    CandidateListResponse,
    CandidateResponse,
    CheckInResponse,
    ErrorResponse,
    ExperimentVariantResponse,
    ExposureRequest,
    ExposureResponse,
    RecommendationResponse,
    SessionCreateRequest,
    SessionFeedbackRequest,
    SessionResponse,
)
from app.domain.experiment.assignment import (
    EXPLANATION_COPY_EXPERIMENT,
    ExperimentError,
    assign,
    get_experiment,
)
from app.domain.outcome.models import SessionOutcome, StateSnapshot, compute_outcome
from app.domain.recommendation.engine import Recommendation
from app.domain.session.service import build_plan
from app.domain.state.models import CheckIn, StateVector
from app.persistence import models
from app.persistence.repositories import (
    CheckInRepository,
    GuestRepository,
    SessionRepository,
)

router = APIRouter(prefix="/v1", tags=["v1"])

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Guest identity required"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Conflicting state"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}


def _to_recommendation_response(
    recommendation: Recommendation,
    catalog: CatalogDep,
    variant: ExperimentVariantResponse | None = None,
) -> RecommendationResponse:
    practice = catalog.practice(recommendation.practice_id)
    return RecommendationResponse(
        **recommendation.model_dump(),
        practice_public_name=practice.public_name,
        explanation_variant=variant,
    )


def _explanation_variant(
    guest_id: uuid.UUID | None, database: DatabaseDep
) -> ExperimentVariantResponse | None:
    """Assign this guest to an explanation-wording variant.

    Presentation only. The recommendation has already been computed by the time
    this runs, so an experiment cannot reach the practice decision even by
    accident.

    A caller with no guest identity gets no variant rather than a random one:
    an assignment that cannot be recorded cannot be analysed either. That case
    opens no database session at all, which is what keeps the recommendation
    endpoint answerable with the database down.
    """
    if guest_id is None:
        return None
    experiment = get_experiment(EXPLANATION_COPY_EXPERIMENT)
    assignment = assign(str(guest_id), experiment)
    with database.session() as session:
        # assignment() creates the guest row if this is its first assignment, so
        # a repeat call is a single lookup.
        GuestRepository(session).assignment(guest_id, assignment)
    return ExperimentVariantResponse(
        experiment_id=assignment.experiment_id, variant=assignment.variant
    )


@router.post(
    "/check-ins",
    operation_id="createCheckIn",
    status_code=status.HTTP_201_CREATED,
    response_model=CheckInResponse,
    responses={422: ERROR_RESPONSES[422]},
    summary="Record a current-state check-in",
)
def create_check_in(
    payload: CheckIn, db: DbSessionDep, guest_id: OptionalGuestDep
) -> CheckInResponse:
    """Guest-first: no account is required and no user identity is created.

    A guest id, if sent, is recorded so the caller can find and delete this data
    later. Without one the check-in is still accepted; it simply has no owner.
    """
    if guest_id is not None:
        GuestRepository(db).touch(guest_id)
    row = CheckInRepository(db).create(payload, guest_id=guest_id)
    return CheckInResponse(id=row.id, created_at=row.created_at, check_in=payload)


@router.post(
    "/recommendations",
    operation_id="createRecommendation",
    status_code=status.HTTP_200_OK,
    response_model=RecommendationResponse,
    responses={422: ERROR_RESPONSES[422]},
    summary="Deterministic practice recommendation",
)
def create_recommendation(
    payload: CheckIn,
    engine: EngineDep,
    catalog: CatalogDep,
    database: DatabaseDep,
    guest_id: OptionalGuestDep,
) -> RecommendationResponse:
    """The recommendation itself is pure computation.

    A session is opened only to record the presentation-experiment assignment,
    and only when the caller sent a guest identity. Without one this endpoint
    still touches no database at all, which is what keeps it answerable with the
    database down.
    """
    recommendation = engine.recommend(payload)
    return _to_recommendation_response(
        recommendation, catalog, _explanation_variant(guest_id, database)
    )


@router.post(
    "/experiments/exposures",
    operation_id="recordExperimentExposure",
    status_code=status.HTTP_200_OK,
    response_model=ExposureResponse,
    responses={k: ERROR_RESPONSES[k] for k in (401, 422)},
    summary="Record that an experiment variant was actually shown",
)
def record_exposure(
    payload: ExposureRequest, db: DbSessionDep, guest_id: RequiredGuestDep
) -> ExposureResponse:
    """Exposure, as distinct from assignment.

    Idempotent per context, so re-opening the same screen does not double-count.
    ``recorded`` says whether this call created the exposure or found one.
    """
    try:
        experiment = get_experiment(payload.experiment_id)
    except ExperimentError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_experiment", "message": "Unknown experiment_id."},
        ) from None

    assignment = assign(str(guest_id), experiment)
    guests = GuestRepository(db)
    guests.assignment(guest_id, assignment)
    _, created = guests.record_exposure(
        guest_id=guest_id,
        experiment_id=assignment.experiment_id,
        variant=assignment.variant,
        context=payload.context,
    )
    return ExposureResponse(
        experiment_id=assignment.experiment_id,
        variant=assignment.variant,
        context=payload.context,
        recorded=created,
    )


@router.post(
    "/sessions",
    operation_id="createSession",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionResponse,
    responses={k: ERROR_RESPONSES[k] for k in (404, 409, 422)},
    summary="Create a session from a stored check-in",
)
def create_session(
    payload: SessionCreateRequest,
    db: DbSessionDep,
    engine: EngineDep,
    catalog: CatalogDep,
    guest_id: OptionalGuestDep,
) -> SessionResponse:
    check_ins = CheckInRepository(db)
    check_in_row = check_ins.get(payload.check_in_id)
    if check_in_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "check_in_not_found", "message": "Unknown check_in_id."},
        )

    recommendation = engine.recommend(CheckInRepository.to_domain(check_in_row))
    if payload.recommendation is not None and payload.recommendation != recommendation:
        # The practice decision belongs to the deterministic engine. A submitted
        # recommendation is accepted only when it matches what the engine derives.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "recommendation_mismatch",
                "message": (
                    "The submitted recommendation does not match the deterministic "
                    "recommendation for this check-in."
                ),
            },
        )

    state = StateVector.from_check_in(CheckInRepository.to_domain(check_in_row))
    plan = build_plan(catalog, recommendation, state=state)
    if guest_id is not None:
        GuestRepository(db).touch(guest_id)
    row = SessionRepository(db).create(
        check_in_id=check_in_row.id,
        recommendation=recommendation,
        plan=plan,
        guest_id=guest_id or check_in_row.guest_id,
        outcome=engine.evaluate(state),
    )
    return SessionResponse(
        id=row.id,
        check_in_id=row.check_in_id,
        status="created",
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        recommendation=_to_recommendation_response(recommendation, catalog),
        plan=plan.as_dict(),  # type: ignore[arg-type]
    )


@router.post(
    "/sessions/{session_id}/start",
    operation_id="startSession",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: ERROR_RESPONSES[404]},
    summary="Mark a session as started",
)
def start_session(session_id: uuid.UUID, db: DbSessionDep) -> Response:
    sessions = SessionRepository(db)
    row = sessions.get(session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Unknown session_id."},
        )
    sessions.mark_started(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/feedback",
    operation_id="submitSessionFeedback",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={k: ERROR_RESPONSES[k] for k in (404, 422)},
    summary="Attach before/after feedback to a session",
)
def submit_session_feedback(
    session_id: uuid.UUID, payload: SessionFeedbackRequest, db: DbSessionDep
) -> Response:
    sessions = SessionRepository(db)
    row = sessions.get(session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Unknown session_id."},
        )
    outcome = _derive_outcome(row, payload, db)
    sessions.upsert_feedback(
        session_id=row.id,
        before_score=payload.before_score,
        after_score=payload.after_score,
        helpfulness=payload.helpfulness,
        completed=payload.completed,
        notes=payload.notes,
        outcome=outcome,
    )
    sessions.finish(row, completed=payload.completed)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _derive_outcome(
    row: models.Session, payload: SessionFeedbackRequest, db: DbSessionDep
) -> SessionOutcome | None:
    """Compute outcome evidence when the client sent a full after-state.

    Partial feedback is accepted and simply produces no derived outcome: half an
    after-state would give a measure for some goals and silently not for others.
    """
    after_values = (
        payload.stress_after,
        payload.energy_after,
        payload.mental_activity_after,
        payload.sleepiness_after,
    )
    if any(value is None for value in after_values):
        return None

    check_in_row = CheckInRepository(db).get(row.check_in_id)
    if check_in_row is None:  # pragma: no cover - foreign key guarantees the row
        return None
    check_in = CheckInRepository.to_domain(check_in_row)
    return compute_outcome(
        goal=check_in.goal,
        before=StateSnapshot(
            stress=check_in.stress,
            energy=check_in.energy,
            mental_activity=check_in.mental_activity,
            sleepiness=check_in.sleepiness,
        ),
        after=StateSnapshot(
            stress=payload.stress_after,  # type: ignore[arg-type]
            energy=payload.energy_after,  # type: ignore[arg-type]
            mental_activity=payload.mental_activity_after,  # type: ignore[arg-type]
            sleepiness=payload.sleepiness_after,  # type: ignore[arg-type]
        ),
        helpfulness=payload.helpfulness,
        completion_ratio=(
            payload.completion_ratio
            if payload.completion_ratio is not None
            else (1.0 if payload.completed else 0.0)
        ),
    )


@router.post(
    "/recommendations/candidates",
    operation_id="createRecommendationCandidates",
    status_code=status.HTTP_200_OK,
    response_model=CandidateListResponse,
    responses={422: ERROR_RESPONSES[422]},
    summary="Full scored candidate list (debug and offline evaluation)",
)
def create_recommendation_candidates(payload: CheckIn, engine: EngineDep) -> CandidateListResponse:
    """Not part of the normal client flow.

    The ordinary recommendation endpoint returns the winner only; this exposes
    the ranking behind it for offline evaluation. Scores are ordinal ranking
    aids, not probabilities.
    """
    outcome = engine.evaluate(StateVector.from_check_in(payload))
    return CandidateListResponse(
        rule_set_version=outcome.rule_set_version,
        candidates=[
            CandidateResponse(
                practice_id=c.practice_id.value,
                score=c.score,
                reason_codes=[code.value for code in c.reason_codes],
            )
            for c in outcome.candidates
        ],
        exclusions=[
            {"practice_id": e.practice_id.value, "reason": e.reason} for e in outcome.exclusions
        ],
    )
