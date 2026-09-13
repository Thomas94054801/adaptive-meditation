"""Test-schema naming and lifecycle.

Program002 and Program003 both lost time to the same defect: two pytest sessions
against one PostgreSQL database destroyed each other, because the schema was
dropped and recreated per session. The fix is that a run never shares a schema
with another run.

Schema names carry their own creation time so a killed run can be swept later
without a side table:

    test_<epoch_seconds>_<run_id>_<worker_id>

Nothing here is imported by production code paths except the guard in
``app.settings``, which exists to make certain that a production process can
never be pointed at one of these.
"""

from __future__ import annotations

import re
import time
import uuid

# Postgres identifiers are 63 bytes. epoch(10) + run(8) + worker(<=8) + separators
# stays well inside that.
TEST_SCHEMA_PREFIX = "test_"
STALE_AFTER_SECONDS = 24 * 60 * 60

# Only these characters may ever reach a CREATE/DROP SCHEMA statement. Schema
# names cannot be bound as parameters, so this is the boundary that keeps an
# identifier from becoming an injection.
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_TEST_SCHEMA = re.compile(rf"^{TEST_SCHEMA_PREFIX}(\d+)_[0-9a-f]{{8}}_[A-Za-z0-9]+$")


class UnsafeSchemaName(ValueError):
    """Raised when an identifier is not safe to interpolate into DDL."""


def assert_safe_identifier(name: str) -> str:
    if not SAFE_IDENTIFIER.match(name):
        raise UnsafeSchemaName(f"unsafe schema identifier: {name!r}")
    return name


def is_test_schema(name: str) -> bool:
    return name.startswith(TEST_SCHEMA_PREFIX)


def new_test_schema(worker_id: str = "main", run_id: str | None = None) -> str:
    """A schema name unique to this invocation and worker."""
    run = run_id or uuid.uuid4().hex[:8]
    worker = re.sub(r"[^A-Za-z0-9]", "", worker_id) or "main"
    return assert_safe_identifier(f"{TEST_SCHEMA_PREFIX}{int(time.time())}_{run}_{worker}")


def schema_age_seconds(name: str, now: float | None = None) -> int | None:
    """Age of a test schema from its embedded timestamp, or None if not ours."""
    match = _TEST_SCHEMA.match(name)
    if not match:
        return None
    return int((now if now is not None else time.time()) - int(match.group(1)))


def is_stale(name: str, now: float | None = None, ttl: int = STALE_AFTER_SECONDS) -> bool:
    """True for a test schema old enough that no live run can still own it.

    Deliberately conservative: a schema younger than the TTL is never swept,
    because a long-running suite must not have its schema pulled out from under
    it by a concurrently starting one.
    """
    age = schema_age_seconds(name, now)
    return age is not None and age > ttl
