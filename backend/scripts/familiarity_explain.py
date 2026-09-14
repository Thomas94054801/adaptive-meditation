"""EXPLAIN (ANALYZE, BUFFERS) for the familiarity count on a 10,000-row guest.

Evidence for PROGRAM005 SDD section 4.3: the count's predicate is the one
``ix_sessions_familiarity`` covers, and this shows what PostgreSQL does with
it on a guest whose history is long and mostly irrelevant. The plan is
printed, not asserted - a small table may seq-scan and be right to.

Runs against DATABASE_URL, which must be PostgreSQL and migrated to head. It
seeds one throwaway guest, explains the exact statement the repository
issues (captured from SQLAlchemy, not retyped), and deletes the guest again.
Local only; never a CI step.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.domain.personalization import EVIDENCE_CAP  # noqa: E402
from app.persistence import models  # noqa: E402
from app.persistence.database import Database  # noqa: E402
from app.persistence.repositories import SessionRepository  # noqa: E402
from app.persistence.seed import TARGET_PRACTICE, seed_history  # noqa: E402
from app.settings import Settings  # noqa: E402


def counting_statement(guest_id: uuid.UUID, practice_id: str, cap: int) -> str:
    """The repository's statement, compiled with literals for EXPLAIN."""
    matches = (
        sa.select(sa.literal(1))
        .where(
            models.Session.guest_id == guest_id,
            models.Session.status == "completed",
            models.Session.recommendation["practice_id"].as_string() == practice_id,
        )
        .limit(cap)
        .subquery("bounded")
    )
    statement = sa.select(sa.func.count()).select_from(matches)
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--matches", type=int, default=3)
    parser.add_argument("--abandoned-target", type=int, default=200)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if not args.database_url.startswith("postgresql"):
        print("PostgreSQL only: SQLite evidence does not substitute", file=sys.stderr)
        return 2

    database = Database(Settings(app_env="test", database_url=args.database_url))
    guest_id = uuid.uuid4()
    lines: list[str] = []
    try:
        with database.session() as session:
            seed_history(
                session,
                guest_id=guest_id,
                rows=args.rows,
                matches=args.matches,
                abandoned_target=args.abandoned_target,
            )
        with database.session() as session:
            session.execute(sa.text("ANALYZE sessions"))
            count = SessionRepository(session).completed_count(
                guest_id, TARGET_PRACTICE, cap=EVIDENCE_CAP
            )
            statement = counting_statement(guest_id, TARGET_PRACTICE, EVIDENCE_CAP)
            plan = session.execute(sa.text(f"EXPLAIN (ANALYZE, BUFFERS) {statement}")).scalars()
            version = session.execute(sa.text("SHOW server_version")).scalar_one()
            lines.append(f"PostgreSQL {version}")
            lines.append(
                f"guest rows={args.rows} matches={args.matches} "
                f"abandoned_target={args.abandoned_target} -> completed_count={count}"
            )
            lines.append("")
            lines.append(statement)
            lines.append("")
            lines.append("-- with ix_sessions_familiarity")
            lines.extend(plan)
        # The same statement with the index gone, inside a transaction that is
        # rolled back: what every session create paid before 0008, and what a
        # LIMIT alone cannot prevent. DDL is transactional on PostgreSQL.
        with database.session() as session:
            session.execute(sa.text("DROP INDEX ix_sessions_familiarity"))
            without = session.execute(sa.text(f"EXPLAIN (ANALYZE, BUFFERS) {statement}")).scalars()
            lines.append("")
            lines.append("-- without ix_sessions_familiarity (rolled back)")
            lines.extend(without)
            session.rollback()
    finally:
        with database.session() as session:
            session.execute(
                sa.delete(models.GuestProfile).where(models.GuestProfile.id == guest_id)
            )
        database.dispose()

    text = "\n".join(lines)
    print(text)
    if args.out:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        args.out.write_text(f"measured_at: {stamp}\n\n{text}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
