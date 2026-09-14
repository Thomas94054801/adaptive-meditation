"""Seeded histories for the familiarity query's benchmark and evidence.

Not test-only: the benchmark script and the EXPLAIN evidence script both need
one guest with a long, mostly irrelevant history, and they need the same one
so their numbers describe the same shape. Rows go in through the ORM in
batches, never one HTTP call each.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as OrmSession

from app.persistence import models
from app.persistence.database import Database

OTHER_PRACTICES = (
    "body_awareness",
    "feeling_tone",
    "thought_observation",
    "kindness",
    "open_awareness",
    "mindful_walking",
)
TARGET_PRACTICE = "breath_awareness"


def _session_row(
    guest_id: uuid.UUID,
    check_in_id: uuid.UUID,
    practice_id: str,
    status: str,
    created_at: datetime,
) -> models.Session:
    return models.Session(
        id=uuid.uuid4(),
        guest_id=guest_id,
        check_in_id=check_in_id,
        recommendation={
            "practice_id": practice_id,
            "duration_minutes": 10,
            "guidance_density": 0.5,
            "reason_codes": [],
        },
        protocol_id=f"{practice_id}_v2",
        protocol_version=2,
        plan={"protocol_id": f"{practice_id}_v2", "public_title": practice_id},
        status=status,
        created_at=created_at,
        completed_at=created_at if status in {"completed", "abandoned"} else None,
        run_state=status if status in {"completed", "abandoned"} else "created",
        elapsed_ms=0,
        command_sequence=0,
    )


def seed_history(
    session: OrmSession,
    *,
    guest_id: uuid.UUID,
    rows: int,
    matches: int,
    target: str = TARGET_PRACTICE,
    abandoned_target: int = 0,
) -> None:
    """``rows`` sessions for one guest, of which exactly ``matches`` are
    completed sessions of ``target``; ``abandoned_target`` more are the target
    practice but abandoned; the rest are completed sessions of other practices.
    """
    if matches + abandoned_target > rows:
        raise ValueError("more special rows than rows")
    session.add(models.GuestProfile(id=guest_id))
    session.flush()
    check_in = models.CheckIn(
        id=uuid.uuid4(),
        guest_id=guest_id,
        goal="overthinking",
        stress=8,
        energy=5,
        mental_activity=9,
        sleepiness=2,
        available_minutes=10,
        experience_level="beginner",
    )
    session.add(check_in)
    session.flush()
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    batch: list[models.Session] = []
    for index in range(rows):
        created_at = origin + timedelta(minutes=index)
        if index < matches:
            row = _session_row(guest_id, check_in.id, target, "completed", created_at)
        elif index < matches + abandoned_target:
            row = _session_row(guest_id, check_in.id, target, "abandoned", created_at)
        else:
            other = OTHER_PRACTICES[index % len(OTHER_PRACTICES)]
            row = _session_row(guest_id, check_in.id, other, "completed", created_at)
        batch.append(row)
        if len(batch) >= 500:
            session.add_all(batch)
            session.flush()
            batch = []
    if batch:
        session.add_all(batch)
        session.flush()


def seed_sparse_history(database: Database, *, rows: int, matches: int) -> tuple[uuid.UUID, str]:
    """Convenience for scripts: a fresh guest, committed. Returns (guest, practice)."""
    guest_id = uuid.uuid4()
    with database.session() as session:
        seed_history(session, guest_id=guest_id, rows=rows, matches=matches)
        session.commit()
    return guest_id, TARGET_PRACTICE
