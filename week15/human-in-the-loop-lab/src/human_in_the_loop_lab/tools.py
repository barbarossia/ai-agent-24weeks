"""Read Tools (auto-executed) and the first Write Tool (approval-gated).

Two tool classes with deliberately different control flow:

* **Read Tools** inspect mock infrastructure state and are safe to
  auto-execute inside the agent flow without asking anyone.
* **Write Tools** change (mock) infrastructure state. ``restart_service``
  is the repository's first Write Tool. It is **never** called from any
  auto-execution path: the graph routes every Write call through the
  ``await_approval`` interrupt node first, and only an ``approve`` resume
  reaches ``execute_write``, the sole caller of the mock backend.

The backend is a mock. Its "restart" is a durable ``mock_service_state``
counter in SQLite — no network, service or subprocess operation is ever
performed. The name ``restart_service`` intentionally matches the Week 3
triage-action vocabulary (``week3/llm-api-lab/.../providers.py`` maps
``"compute"`` trouble to a ``"restart_service"`` action string); that
Week 3 string is not a tool implementation and is left untouched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolExecutionError(Exception):
    """Mock backend cannot satisfy the request (unknown host/service)."""


# ---------------------------------------------------------------------------
# Mock infrastructure data (stands in for a real HomeLab API).
# ---------------------------------------------------------------------------

_HOST_STATUS = {
    "web01": {"status": "degraded", "latency_ms": 210},
    "db01": {"status": "up", "latency_ms": 34},
    "esxi01": {"status": "down", "latency_ms": None},
}

_SERVICE_REGISTRY = {
    "web01": ["nginx", "app"],
    "db01": ["postgres"],
    "esxi01": ["vcenter"],
}

# Services that "fail to restart" in the mock backend, to exercise the
# execution-failure audit path (H004 requirement 8 / H002 R4).
FAILING_SERVICES = {"boom"}


# ---------------------------------------------------------------------------
# Read Tools: safe, side-effect free, auto-executed by the agent.
# ---------------------------------------------------------------------------


def get_host_status(host: str) -> dict[str, Any]:
    """Read Tool: return mock up/down status for a host."""
    record = _HOST_STATUS.get(host)
    if record is None:
        raise ToolExecutionError(f"unknown host: {host!r}")
    return {"host": host, **record}


def list_services(host: str) -> dict[str, Any]:
    """Read Tool: return the mock service list managed on a host."""
    services = _SERVICE_REGISTRY.get(host)
    if services is None:
        raise ToolExecutionError(f"no service data for host: {host!r}")
    return {"host": host, "services": services}


class HostArgs(BaseModel):
    model_config = {"extra": "forbid"}

    host: str = Field(min_length=1, max_length=64, description="Host name, e.g. 'web01'")


class ServiceArgs(BaseModel):
    model_config = {"extra": "forbid"}

    service: str = Field(min_length=1, max_length=64, description="Service name, e.g. 'nginx'")


class Permission(Enum):
    READ = "read"
    WRITE = "write"


READ_TOOLS: dict[str, dict[str, Any]] = {
    "get_host_status": {
        "description": "Get up/down status and latency for a named host.",
        "args_model": HostArgs,
        "func": get_host_status,
        "permission": Permission.READ,
    },
    "list_services": {
        "description": "List the services managed on a named host.",
        "args_model": HostArgs,
        "func": list_services,
        "permission": Permission.READ,
    },
}

WRITE_TOOLS: dict[str, dict[str, Any]] = {
    "restart_service": {
        "description": "Write Tool: restart a named service (mock backend; requires human approval).",
        "args_model": ServiceArgs,
        "func": None,  # no auto-execution path exists for Write Tools
        "permission": Permission.WRITE,
    },
}


# ---------------------------------------------------------------------------
# Mock Write backend for restart_service.
#
# H006-F1 correction (H007): the mock restart mutation and its idempotency
# key are applied in ONE SQLite transaction. ``restart_service`` claims
# ``effect_key`` (INSERT OR IGNORE) and, only if it is the claimant, applies
# the mock service-state mutation (``mock_service_state.restarts += 1``)
# and records the outcome — all inside a single ``BEGIN IMMEDIATE``
# transaction. Either the restart and its key commit together, or neither
# does; a retry after any crash finds the committed pair and returns the
# recorded result without applying the effect again. This is exactly-once
# for the transactional mock only; a real external service cannot join
# this transaction and needs its own idempotency support or an
# outbox/reconciliation protocol (Week 14's documented boundary).
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS write_effects (
    effect_key TEXT PRIMARY KEY,
    effect TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mock_service_state (
    service TEXT PRIMARY KEY,
    restarts INTEGER NOT NULL,
    last_restarted_at REAL NOT NULL
);
"""


def restart_service(
    service: str,
    *,
    db_path: Path,
    effect_key: str,
    call_log: Path | None = None,
    crash_before_commit: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Mock Write backend: atomically claim ``effect_key`` and apply one restart.

    One ``BEGIN IMMEDIATE`` transaction does all of: claim the idempotency
    key, apply the mock restart mutation (``mock_service_state.restarts
    += 1``), and persist the resulting outcome on the key's row. Returns
    ``(applied, result)``: ``applied`` is True only for the invocation
    whose transaction performed the mutation; every later invocation with
    the same key returns the recorded outcome unchanged.

    ``call_log`` (optional) appends one line per *applied* restart after
    the transaction commits, as a human-readable attempt trace. It is
    evidence only — the authoritative restart state is the committed
    ``mock_service_state`` row, so a crash between the commit and the
    log append can leave the trace one line short (never one line over).

    ``crash_before_commit`` is a test hook that terminates the process
    (exit 93) after the mutation statements run but before the transaction
    commits, proving the whole transaction rolls back and the retry
    re-applies it exactly once.

    Raises ``ToolExecutionError`` for services in ``FAILING_SERVICES``
    before any claim is taken. Never contacts a real service.
    """
    if service in FAILING_SERVICES:
        if call_log is not None:
            with call_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"service": service, "attempted": True}) + "\n")
        raise ToolExecutionError(f"mock restart failed for service: {service!r}")

    with closing(sqlite3.connect(db_path)) as connection:
        connection.isolation_level = None  # explicit transaction control
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        for statement in _SCHEMA.strip().split(";"):
            if statement.strip():
                connection.execute(statement)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO write_effects(effect_key, effect) VALUES (?, ?)",
            (effect_key, json.dumps({"service": service, "state": "pending"}, sort_keys=True)),
        )
        if cursor.rowcount == 1:
            # Claimant: apply the restart mutation in this same transaction.
            connection.execute(
                """INSERT INTO mock_service_state(service, restarts, last_restarted_at)
                   VALUES (?, 1, ?)
                   ON CONFLICT(service) DO UPDATE
                   SET restarts = restarts + 1,
                       last_restarted_at = excluded.last_restarted_at""",
                (service, time.time()),
            )
            restarts = int(
                connection.execute(
                    "SELECT restarts FROM mock_service_state WHERE service = ?", (service,)
                ).fetchone()[0]
            )
            result = {"service": service, "restarted": True, "restarts": restarts}
            connection.execute(
                "UPDATE write_effects SET effect = ? WHERE effect_key = ?",
                (json.dumps(result, sort_keys=True), effect_key),
            )
            if crash_before_commit:
                print(
                    "mock restart staged; crashing BEFORE effect transaction commit (exit 93)",
                    flush=True,
                )
                os._exit(93)
            connection.execute("COMMIT")
            applied = True
        else:
            # Replay: the claim+mutation pair already committed in an
            # earlier (crashed or completed) attempt; return it untouched.
            recorded = connection.execute(
                "SELECT effect FROM write_effects WHERE effect_key = ?", (effect_key,)
            ).fetchone()[0]
            result = json.loads(recorded)
            connection.execute("COMMIT")
            applied = False

    if applied and call_log is not None:
        with call_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"service": service}) + "\n")
    return applied, result


def _write_call_log_path() -> Path | None:
    path = os.environ.get("HITL_CALL_LOG")
    return Path(path) if path else None


def restart_service_from_env(
    service: str,
    *,
    db_path: Path,
    effect_key: str,
    crash_before_commit: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """``restart_service`` bound to the ``HITL_CALL_LOG`` evidence file."""
    return restart_service(
        service,
        db_path=db_path,
        effect_key=effect_key,
        call_log=_write_call_log_path(),
        crash_before_commit=crash_before_commit,
    )


def service_restart_counts(db_path: Path) -> dict[str, int]:
    """Return the committed mock restart count per service (test/demo aid)."""
    if not db_path.exists():
        return {}
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mock_service_state'"
        ).fetchone()
        if table is None:
            return {}
        rows = connection.execute("SELECT service, restarts FROM mock_service_state").fetchall()
    return {service: int(count) for service, count in rows}


def read_write_effect(db_path: Path, effect_key: str) -> dict[str, Any] | None:
    """Return the recorded effect payload for ``effect_key`` if committed."""
    if not db_path.exists():
        return None
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='write_effects'"
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            "SELECT effect FROM write_effects WHERE effect_key = ?", (effect_key,)
        ).fetchone()
        return json.loads(row[0]) if row else None


__all__ = [
    "READ_TOOLS",
    "WRITE_TOOLS",
    "Permission",
    "ToolExecutionError",
    "HostArgs",
    "ServiceArgs",
    "get_host_status",
    "list_services",
    "restart_service",
    "restart_service_from_env",
    "service_restart_counts",
    "read_write_effect",
    "FAILING_SERVICES",
]
