"""Crash-idempotent Audit Log for the Week 15 approval flow.

Every logical event (proposal, decision, execution result/failure,
rejection) gets a globally unique ``event_key`` written through
``INSERT OR IGNORE`` — the same exactly-once pattern Week 14 uses for its
``mock_effects`` table. Because LangGraph re-executes an interrupted node
from its start on resume, a node's audit writes can run twice across a
crash/retry; the unique key makes the second write a no-op instead of a
duplicate row.

Key scheme (correlation identity = thread id; version bumps on every edit
so a re-approved, edited proposal can never collide with the superseded
one's keys):

===========================  ==================================================
event type                   key shape
===========================  ==================================================
``proposal``                 ``{thread_id}:proposal:v{version}``
``decision:approve/reject/`` ``{thread_id}:decision:{ordinal}:{action}:v{version}``
``decision:edit``            (same as above; the payload carries the edit)
``executed``                 ``{thread_id}:executed:v{version}``
``execution_failed``         ``{thread_id}:failed:v{version}``
``rejected``                 ``{thread_id}:rejected:v{version}``
===========================  ==================================================

``ordinal`` is the per-thread decision counter, so repeated decisions
against the same version (e.g. edit self-loops) never collide.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class AuditEvent(BaseModel):
    event_key: str
    thread_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: float


def _clock() -> float:
    return time.time()


def init_audit_log(db_path: Path) -> None:
    """Create the audit table if it does not exist (idempotent)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                   event_key TEXT PRIMARY KEY,
                   thread_id TEXT NOT NULL,
                   event_type TEXT NOT NULL,
                   payload TEXT NOT NULL,
                   created_at REAL NOT NULL
               )"""
        )
        connection.commit()


def audit_once(
    db_path: Path,
    event_key: str,
    thread_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    clock: Any = None,
) -> bool:
    """Write one audit event; return True only on its first commit.

    ``INSERT OR IGNORE`` on the ``event_key`` PRIMARY KEY makes repeated
    writes of the same logical event (node re-execution after a crash
    between audit commit and checkpoint commit) idempotent.
    """
    now = (clock or _clock)()
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                   event_key TEXT PRIMARY KEY,
                   thread_id TEXT NOT NULL,
                   event_type TEXT NOT NULL,
                   payload TEXT NOT NULL,
                   created_at REAL NOT NULL
               )"""
        )
        cursor = connection.execute(
            """INSERT OR IGNORE INTO audit_log
                   (event_key, thread_id, event_type, payload, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_key, thread_id, event_type, json.dumps(payload, sort_keys=True), now),
        )
        connection.commit()
        return cursor.rowcount == 1


def read_audit(db_path: Path, thread_id: str | None = None) -> list[AuditEvent]:
    """Return audit rows in commit order, optionally filtered by thread."""
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ).fetchone()
        if table is None:
            return []
        if thread_id is None:
            rows = connection.execute(
                "SELECT event_key, thread_id, event_type, payload, created_at "
                "FROM audit_log ORDER BY rowid"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT event_key, thread_id, event_type, payload, created_at "
                "FROM audit_log WHERE thread_id = ? ORDER BY rowid",
                (thread_id,),
            ).fetchall()
    return [
        AuditEvent(
            event_key=row[0],
            thread_id=row[1],
            event_type=row[2],
            payload=json.loads(row[3]),
            created_at=row[4],
        )
        for row in rows
    ]


def audit_count(db_path: Path, event_type: str, thread_id: str) -> int:
    """Count audit rows of one type for one thread (dedup assertions)."""
    events = read_audit(db_path, thread_id)
    return sum(1 for event in events if event.event_type == event_type)


# ---------------------------------------------------------------------------
# Event key builders (single source of truth for the key scheme).
# ---------------------------------------------------------------------------


def proposal_key(thread_id: str, version: int) -> str:
    return f"{thread_id}:proposal:v{version}"


def decision_key(thread_id: str, ordinal: int, action: str, version: int) -> str:
    return f"{thread_id}:decision:{ordinal}:{action}:v{version}"


def executed_key(thread_id: str, version: int) -> str:
    return f"{thread_id}:executed:v{version}"


def failed_key(thread_id: str, version: int) -> str:
    return f"{thread_id}:failed:v{version}"


def rejected_key(thread_id: str, version: int) -> str:
    return f"{thread_id}:rejected:v{version}"


def write_effect_key(thread_id: str, version: int) -> str:
    """Idempotency key for the restart_service write effect itself."""
    return f"{thread_id}:execute:v{version}"


__all__ = [
    "AuditEvent",
    "init_audit_log",
    "audit_once",
    "read_audit",
    "audit_count",
    "proposal_key",
    "decision_key",
    "executed_key",
    "failed_key",
    "rejected_key",
    "write_effect_key",
]
