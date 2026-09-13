"""v1 endpoints for the check-in -> recommendation -> session -> feedback slice."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.adapters.audio.registry import build_renderer
from app.api.deps import (
    CatalogDep,
    DatabaseDep,
    DbSessionDep,
    EngineDep,
    OptionalGuestDep,
    RequiredGuestDep,
    SettingsDep,
)
from app.api.v1.schemas import (
    CandidateListResponse,
    CandidateResponse,
    CheckInResponse,
    ErrorResponse,
    ExperimentVariantResponse,
    ExposureRequest,
    ExposureResponse,
    PlaybackCommandRequest,
    PlaybackStateResponse,
    RecommendationResponse,
    RenderManifestEntryResponse,
    RenderManifestResponse,
    SessionCreateRequest,
    SessionEventBatchRequest,
    SessionEventBatchResponse,
    SessionFeedbackRequest,
    SessionResponse,
)
from app.domain.audio.coordinator import build_manifest
from app.domain.audio.render import RenderResult
from app.domain.experiment.assignment import (
    EXPLANATION_COPY_EXPERIMENT,
    ExperimentError,
    assign,
    get_experiment,
)
from app.domain.outcome.models import SessionOutcome, StateSnapshot, compute_outcome
from app.domain.playback.state_machine import InvalidTransition
from app.domain.recommendation.engine import Recommendation
from app.domain.session.service import build_plan
from app.domain.state.models import CheckIn, StateVector
from app.domain.timeline.planner_v2 import (
    PLAN_TIME_STYLE as DEFAULT_STYLE,
)
from app.domain.timeline.planner_v2 import (
    PLAN_TIME_VOICE as DEFAULT_VOICE_ID,
)
from app.domain.timeline.planner_v2 import SessionPlanV2
from app.domain.timeline.service import (
    apply_command,
    plan_response_payload,
    plan_session,
    recovery_point,
)
from app.persistence import models
from app.persistence.repositories import (
    AudioRenderRepository,
    CheckInRepository,
    EventDraft,
    GuestRepository,
    SessionDefinitionRepository,
    SessionEventRepository,
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

    # Freeze the content before planning against it, so the session keeps
    # describing the words it actually used after the knowledge files move on.
    planned = plan_session(catalog, recommendation, state)
    SessionDefinitionRepository(db).ensure(planned.definition)

    if guest_id is not None:
        GuestRepository(db).touch(guest_id)
    row = SessionRepository(db).create(
        check_in_id=check_in_row.id,
        recommendation=recommendation,
        plan=plan,
        guest_id=guest_id or check_in_row.guest_id,
        outcome=engine.evaluate(state),
        plan_v2=plan_response_payload(planned.plan),
        plan_hash=planned.plan.plan_hash,
        definition_id=planned.definition.definition_id,
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
        plan_v2=plan_response_payload(planned.plan),  # type: ignore[arg-type]
        run_state=row.run_state,
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


@router.get(
    "/sessions/{session_id}",
    operation_id="getSession",
    response_model=SessionResponse,
    responses={k: ERROR_RESPONSES[k] for k in (401, 404)},
    summary="Read a session, including its recovery point",
)
def get_session(
    session_id: uuid.UUID, db: DbSessionDep, catalog: CatalogDep, guest_id: RequiredGuestDep
) -> SessionResponse:
    row = _owned_session(session_id, guest_id, db)
    recommendation = Recommendation.from_stored(dict(row.recommendation))
    return SessionResponse(
        id=row.id,
        check_in_id=row.check_in_id,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        recommendation=_to_recommendation_response(recommendation, catalog),
        plan=dict(row.plan),  # type: ignore[arg-type]
        plan_v2=dict(row.plan_v2) if row.plan_v2 else None,  # type: ignore[arg-type]
        run_state=row.run_state,
    )


@router.post(
    "/sessions/{session_id}/playback",
    operation_id="applyPlaybackCommand",
    response_model=PlaybackStateResponse,
    responses={k: ERROR_RESPONSES[k] for k in (401, 404, 409, 422)},
    summary="Apply a playback command",
)
def apply_playback_command(
    session_id: uuid.UUID,
    payload: PlaybackCommandRequest,
    db: DbSessionDep,
    guest_id: RequiredGuestDep,
) -> PlaybackStateResponse:
    """Drive the run state machine.

    A replayed sequence, an out-of-order sequence and a command on a finished
    run all return the current state with ``applied=false``. Two things are a
    409: an illegal transition - starting a session that was never prepared -
    and a sequence the journal already holds.
    """
    row = _owned_session(session_id, guest_id, db)
    events = SessionEventRepository(db)
    if events.command_already_applied(row.id, payload.command_id):
        # SDD 5.4: a replayed command_id returns the same result without
        # re-applying it. The sequence rule below catches an identical retry;
        # this catches the same command retried under a fresh sequence.
        return _playback_state(row, applied=False)

    try:
        outcome = apply_command(
            current_state=row.run_state,
            current_sequence=row.command_sequence,
            current_elapsed_ms=row.elapsed_ms,
            current_segment_id=row.last_segment_id,
            command=payload.command,
            sequence=payload.sequence,
            elapsed_ms=payload.elapsed_ms,
            segment_id=payload.segment_id,
        )
    except InvalidTransition as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_transition", "message": str(error)},
        ) from None

    if outcome.applied:
        sessions = SessionRepository(db)
        row.run_state = outcome.state.value
        row.elapsed_ms = outcome.elapsed_ms
        row.last_segment_id = outcome.last_segment_id
        row.command_sequence = outcome.sequence
        # Keep the Program001 status column in step, so history and outcome
        # reporting keep working without knowing about run states.
        if outcome.state.value == "playing" and row.started_at is None:
            sessions.mark_started(row)
        elif outcome.state.value == "completed":
            sessions.finish(row, completed=True)
        elif outcome.state.value == "abandoned":
            sessions.finish(row, completed=False)

        _, created = events.append(
            session_id=row.id,
            sequence=payload.sequence,
            event_type=_EVENT_FOR_COMMAND[payload.command],
            segment_id=payload.segment_id,
            elapsed_ms=outcome.elapsed_ms,
            command_id=payload.command_id,
        )
        if not created:
            # Commands and events share one per-session counter. A command that
            # lands on a sequence already holding something else means the
            # client's counter is broken, and applying the state change while
            # losing its journal entry would leave a run nobody can reconstruct.
            # Raising rolls the whole request back.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "sequence_conflict",
                    "message": f"sequence {payload.sequence} is already recorded.",
                },
            )

    return _playback_state(row, applied=outcome.applied)


@router.post(
    "/sessions/{session_id}/prepare",
    operation_id="prepareSession",
    response_model=RenderManifestResponse,
    responses={k: ERROR_RESPONSES[k] for k in (401, 404, 409)},
    summary="Resolve the audio a session needs",
)
def prepare_session(
    session_id: uuid.UUID,
    db: DbSessionDep,
    guest_id: RequiredGuestDep,
    settings: SettingsDep,
) -> RenderManifestResponse:
    """Build the render manifest for a session's speech segments.

    Cache first, renderer only on a miss, which is what makes synthesis a
    one-off cost rather than a per-session one. With no server-side renderer
    configured - the shipping default - every segment comes back unresolved and
    the client speaks them with device-native TTS.
    """
    row = _owned_session(session_id, guest_id, db)
    if not row.plan_v2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "no_typed_plan",
                "message": "This session predates typed plans and cannot be prepared.",
            },
        )

    plan = SessionPlanV2.from_dict(dict(row.plan_v2))
    renders = AudioRenderRepository(db)
    renderer = build_renderer(settings.speech_provider, app_env=settings.app_env)
    manifest = build_manifest(plan, renderer, renders.get)

    for entry in manifest.entries:
        if not entry.from_cache:
            renders.record(
                RenderResult(
                    render_key=entry.render_key,
                    duration_ms=entry.duration_ms,
                    content_sha256=entry.content_sha256,
                    uri=entry.uri,
                    provider_id=renderer.provider_id,
                    provider_version=renderer.provider_version,
                    byte_size=0,
                ),
                locale=plan.locale,
                voice_id=DEFAULT_VOICE_ID,
                style=DEFAULT_STYLE,
            )

    return RenderManifestResponse(
        session_id=row.id,
        plan_hash=plan.plan_hash,
        provider_id=renderer.provider_id,
        locale=plan.locale,
        entries=[
            RenderManifestEntryResponse(**entry.as_dict())  # type: ignore[arg-type]
            for entry in manifest.entries
        ],
        unresolved=list(manifest.unresolved),
        complete=manifest.complete,
    )


@router.get(
    "/sessions/{session_id}/playback",
    operation_id="getPlaybackState",
    response_model=PlaybackStateResponse,
    responses={k: ERROR_RESPONSES[k] for k in (401, 404)},
    summary="Read playback state and the recovery point",
)
def get_playback_state(
    session_id: uuid.UUID, db: DbSessionDep, guest_id: RequiredGuestDep
) -> PlaybackStateResponse:
    """What a client asks for after being killed in the background."""
    return _playback_state(_owned_session(session_id, guest_id, db), applied=False)


@router.post(
    "/sessions/{session_id}/events",
    operation_id="appendSessionEvents",
    response_model=SessionEventBatchResponse,
    responses={k: ERROR_RESPONSES[k] for k in (401, 404, 422)},
    summary="Append playback events",
)
def append_session_events(
    session_id: uuid.UUID,
    payload: SessionEventBatchRequest,
    db: DbSessionDep,
    guest_id: RequiredGuestDep,
) -> SessionEventBatchResponse:
    """Batched so a session does not make a round trip per segment.

    Idempotent per (session, sequence): a client that retries after losing its
    connection re-sends the batch and gets the same journal, not a doubled one.
    """
    row = _owned_session(session_id, guest_id, db)
    accepted, duplicates = SessionEventRepository(db).append_many(
        row.id,
        [
            EventDraft(
                sequence=event.sequence,
                event_type=event.event_type,
                segment_id=event.segment_id,
                elapsed_ms=event.elapsed_ms,
                command_id=event.command_id,
                detail=event.detail,
            )
            for event in payload.events
        ],
    )
    return SessionEventBatchResponse(accepted=accepted, duplicates=duplicates)


_EVENT_FOR_COMMAND = {
    "prepare": "session_created",
    "resolved": "session_prepared",
    "unresolvable": "render_failure",
    "start": "session_started",
    "pause": "playback_paused",
    "resume": "playback_resumed",
    "interrupt": "playback_interrupted",
    # An interruption ending is its own fact, not a second pause: the run stays
    # paused, and conflating the two would make the journal unable to say why.
    "interruption_ended": "playback_focus_regained",
    "complete": "session_completed",
    "abandon": "session_abandoned",
    "fail": "playback_failed",
    "recover": "session_prepared",
}


def _playback_state(row: models.Session, *, applied: bool) -> PlaybackStateResponse:
    segment_id, offset_ms = (None, 0)
    if row.plan_v2:
        segment_id, offset_ms = recovery_point(
            SessionPlanV2.from_dict(dict(row.plan_v2)), row.last_segment_id
        )
    return PlaybackStateResponse(
        session_id=row.id,
        run_state=row.run_state or "created",
        elapsed_ms=row.elapsed_ms,
        last_segment_id=row.last_segment_id,
        command_sequence=row.command_sequence,
        applied=applied,
        resume_segment_id=segment_id,
        resume_offset_ms=offset_ms,
    )


def _owned_session(session_id: uuid.UUID, guest_id: uuid.UUID, db: DbSessionDep) -> models.Session:
    """Fetch a session the caller owns.

    A session belonging to another guest is reported as not found rather than
    forbidden: confirming it exists would leak that it does.
    """
    row = SessionRepository(db).get(session_id)
    if row is None or row.guest_id != guest_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Unknown session_id."},
        )
    return row
