"""Week 15 acceptance tests, mapped to the H004 required properties.

Crash/retry tests follow H003's corrected design: a genuine process exit
(``os._exit``) inside the hazardous window, then a fresh process proving
idempotency — not merely resuming an already-completed thread.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
THREAD_ID = "week15-test-thread"


def run_cli(
    db_path: Path, *args: str, env_extra: dict[str, str] | None = None, thread_id: str = THREAD_ID
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "human_in_the_loop_lab.cli", "--db", str(db_path),
         "--thread-id", thread_id, *args],
        cwd=PROJECT_DIR, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=60, check=False,
    )


def call_log_lines(path: Path) -> list[dict]:
    """Backend invocations recorded outside the SQLite machinery under test."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def audit_rows(db_path: Path) -> list[tuple[str, str]]:
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ).fetchone()
        if table is None:
            return []
        rows = connection.execute(
            "SELECT event_key, event_type FROM audit_log WHERE thread_id = ? ORDER BY rowid",
            (THREAD_ID,),
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def event_types(db_path: Path) -> list[str]:
    return [event_type for _, event_type in audit_rows(db_path)]


def service_restarts(db_path: Path, service: str) -> int:
    """Committed mock restart count for one service (authoritative state)."""
    if not db_path.exists():
        return 0
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mock_service_state'"
        ).fetchone()
        if table is None:
            return 0
        row = connection.execute(
            "SELECT restarts FROM mock_service_state WHERE service = ?", (service,)
        ).fetchone()
    return int(row[0]) if row else 0


def effect_key_rows(db_path: Path) -> int:
    """Committed rows in write_effects (any state)."""
    if not db_path.exists():
        return 0
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='write_effects'"
        ).fetchone()
        if table is None:
            return 0
        return int(connection.execute("SELECT COUNT(*) FROM write_effects").fetchone()[0])


def inspect_state(db_path: Path) -> dict:
    inspected = run_cli(db_path, "inspect")
    assert inspected.returncode == 0, inspected.stderr
    return json.loads(inspected.stdout)


# ---------------------------------------------------------------------------
# Property 1/11: Read Tools auto-execute; the Write Tool pauses for approval.
# ---------------------------------------------------------------------------


def test_start_auto_executes_reads_and_pauses_at_approval(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"

    started = run_cli(db_path, "start", "--host", "web01")
    assert started.returncode == 0, started.stderr
    assert "PENDING APPROVAL" in started.stdout

    state = inspect_state(db_path)
    assert state["next"] == ["await_approval"]  # paused before any write
    assert state["pending_proposal"]["proposal"]["tool"] == "restart_service"
    assert state["values"]["proposal"]["args"] == {"service": "nginx"}
    # Both Read Tools ran automatically during the same start invocation.
    assert "PENDING APPROVAL" in started.stdout
    # Proposal is audited; nothing has executed yet.
    assert "proposal" in event_types(db_path)
    assert "executed" not in event_types(db_path)


# ---------------------------------------------------------------------------
# Property: restart_service is not called before approval (pending state).
# ---------------------------------------------------------------------------


def test_no_service_call_before_approval(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"

    started = run_cli(db_path, "start", "--host", "web01",
                      env_extra={"HITL_CALL_LOG": str(call_log)})
    assert started.returncode == 0, started.stderr
    assert call_log_lines(call_log) == []
    assert "executed" not in event_types(db_path)


# ---------------------------------------------------------------------------
# Property 4/9: approve executes exactly once and resumes the Agent flow;
# second resume on a completed thread is a no-op (smoke, not the retry proof).
# ---------------------------------------------------------------------------


def test_approve_executes_once_and_resumes_agent(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0
    approved = run_cli(db_path, "approve", env_extra=env)
    assert approved.returncode == 0, approved.stderr
    outcome = json.loads(approved.stdout)
    assert outcome["execution_status"] == "executed"
    assert outcome["agent_observation"] == "agent-resumed:executed"  # R5
    assert "execute:nginx" in outcome["calls"]
    assert outcome["calls"][-1] == "agent-resumed:executed"  # resume edge ran after execute

    assert call_log_lines(call_log) == [{"service": "nginx"}]
    types = event_types(db_path)
    assert types.count("executed") == 1
    assert types.count("decision:approve") == 1

    # Completed-thread resume is a no-op (regression only; the exactly-once
    # under-retry claim is proven by the crash tests below).
    again = run_cli(db_path, "approve", env_extra=env)
    assert again.returncode == 0
    assert "Thread already complete" in again.stdout
    assert call_log_lines(call_log) == [{"service": "nginx"}]
    assert event_types(db_path).count("executed") == 1


# ---------------------------------------------------------------------------
# Property: reject has no service side effect; ends with rejection observation.
# ---------------------------------------------------------------------------


def test_reject_has_no_side_effect_and_ends_with_rejection(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"

    assert run_cli(db_path, "start", "--host", "web01",
                   env_extra={"HITL_CALL_LOG": str(call_log)}).returncode == 0
    rejected = run_cli(db_path, "reject")
    assert rejected.returncode == 0, rejected.stderr
    outcome = json.loads(rejected.stdout)
    assert outcome["agent_observation"] == "agent-resumed:rejected"
    assert "rejected-end" in outcome["calls"]
    assert all(not call.startswith("execute:") for call in outcome["calls"])

    assert call_log_lines(call_log) == []
    types = event_types(db_path)
    assert "executed" not in types
    assert "execution_failed" not in types
    assert types.count("decision:reject") == 1
    assert types.count("rejected") == 1


# ---------------------------------------------------------------------------
# Property 3: edit requires a new approval bound to the edited payload.
# ---------------------------------------------------------------------------


def test_edit_requires_new_approval_and_executes_edited_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0
    edited = run_cli(db_path, "edit", "--service", "postgres", env_extra=env)
    assert edited.returncode == 0, edited.stderr

    state = inspect_state(db_path)
    assert state["next"] == ["await_approval"]  # re-entered approval
    assert state["pending_proposal"]["proposal"]["args"] == {"service": "postgres"}
    assert state["values"]["proposal_version"] == 2
    assert call_log_lines(call_log) == []  # the edit itself never executes
    types = event_types(db_path)
    assert types.count("decision:edit") == 1
    assert types.count("proposal") == 2  # v1 + edited v2
    assert "executed" not in types

    approved = run_cli(db_path, "approve", env_extra=env)
    assert approved.returncode == 0, approved.stderr
    outcome = json.loads(approved.stdout)
    assert outcome["execution_status"] == "executed"
    assert "execute:postgres" in outcome["calls"]  # edited payload, not nginx
    assert call_log_lines(call_log) == [{"service": "postgres"}]
    types = event_types(db_path)
    assert types.count("executed") == 1
    assert types.count("decision:approve") == 1


# ---------------------------------------------------------------------------
# Property 8: backend failure after approval -> durable failure audit only.
# ---------------------------------------------------------------------------


def test_execution_failure_audited_without_success(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0
    assert run_cli(db_path, "edit", "--service", "boom", env_extra=env).returncode == 0
    approved = run_cli(db_path, "approve", env_extra=env)
    assert approved.returncode == 0, approved.stderr
    outcome = json.loads(approved.stdout)
    assert outcome["execution_status"] == "failed"
    assert outcome["agent_observation"] == "agent-resumed:failed"

    types = event_types(db_path)
    assert types.count("execution_failed") == 1
    assert "executed" not in types  # no misleading success event
    assert call_log_lines(call_log) == [{"service": "boom", "attempted": True}]  # attempted once, then failed


# ---------------------------------------------------------------------------
# Property 6 (H002 R1, BLOCKING): genuine execute-node crash/retry.
# Effect committed, checkpoint not: retry re-enters execute_write from its
# start; the backend's atomic claim+mutation transaction — not "thread
# complete" — is what prevents the second restart.
# ---------------------------------------------------------------------------


def test_crash_after_effect_retry_calls_backend_once(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0

    # Approve; crash (exit 92) after the effect/audit commit, before the
    # node update is checkpointed and before resume_agent runs.
    crashed = run_cli(db_path, "approve", "--crash-after-effect", env_extra=env)
    assert crashed.returncode == 92, crashed.stderr
    assert "write effect committed; crashing" in crashed.stdout
    assert call_log_lines(call_log) == [{"service": "nginx"}]  # effect did commit
    assert service_restarts(db_path, "nginx") == 1

    # Fresh process: LangGraph genuinely considers execute_write incomplete.
    state = inspect_state(db_path)
    assert state["next"] == ["execute_write"], state

    # Retry: plain invoke(None) (no new Command); the node re-runs from its
    # start and must take the replay path, not a second backend call.
    resumed = run_cli(db_path, "retry", env_extra=env)
    assert resumed.returncode == 0, resumed.stderr
    final = inspect_state(db_path)
    assert final["next"] == []
    assert final["values"]["execution_status"] == "executed"
    assert final["values"]["agent_observation"] == "agent-resumed:executed"
    assert "execute:replayed" in final["values"]["calls"]
    assert call_log_lines(call_log) == [{"service": "nginx"}]  # exactly once
    assert service_restarts(db_path, "nginx") == 1  # mock state: still one restart
    types = event_types(db_path)
    assert types.count("executed") == 1
    assert types.count("decision:approve") == 1
    assert effect_key_rows(db_path) == 1  # exactly one committed effect key


# ---------------------------------------------------------------------------
# H006-F1 (BLOCKING, H007 request §3): the exact gap H006 demonstrated —
# a crash between the backend invocation and the idempotency-marker
# commit. With the transactional backend the whole claim+mutation rolls
# back atomically, and the retry re-applies it exactly once.
# ---------------------------------------------------------------------------


def test_crash_before_effect_commit_retry_applies_restart_once(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0

    # Approve; crash (exit 93) INSIDE the backend transaction: the restart
    # mutation statements ran, but the transaction never committed.
    crashed = run_cli(db_path, "approve", "--crash-before-commit", env_extra=env)
    assert crashed.returncode == 93, crashed.stderr
    assert "crashing BEFORE effect transaction commit" in crashed.stdout

    # The atomic rollback left NO claim, NO mutation, NO audit row.
    assert effect_key_rows(db_path) == 0
    assert service_restarts(db_path, "nginx") == 0
    assert "executed" not in event_types(db_path)
    assert call_log_lines(call_log) == []

    # Fresh process: execute_write is genuinely incomplete and re-runs.
    state = inspect_state(db_path)
    assert state["next"] == ["execute_write"], state

    # Retry: the backend transaction now commits; the restart applies once.
    resumed = run_cli(db_path, "retry", env_extra=env)
    assert resumed.returncode == 0, resumed.stderr
    final = inspect_state(db_path)
    assert final["next"] == []
    assert final["values"]["execution_status"] == "executed"
    assert final["values"]["agent_observation"] == "agent-resumed:executed"

    # Exactly one restart, one effect key, one executed audit event.
    assert service_restarts(db_path, "nginx") == 1
    assert effect_key_rows(db_path) == 1
    assert event_types(db_path).count("executed") == 1
    assert call_log_lines(call_log) == [{"service": "nginx"}]

    # A second retry on the completed thread changes nothing (smoke).
    assert run_cli(db_path, "retry", env_extra=env).returncode == 0
    assert service_restarts(db_path, "nginx") == 1
    assert effect_key_rows(db_path) == 1


# ---------------------------------------------------------------------------
# Property 7 (H002 R2, BLOCKING): crash between decision-audit commit and
# the owning node's checkpoint commit; retry must not duplicate audit rows.
# ---------------------------------------------------------------------------


def test_crash_after_decision_audit_retry_keeps_single_decision_row(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0

    # Approve; crash (exit 91) after the decision audit row commits, before
    # await_approval returns its update. execute_write never ran here.
    crashed = run_cli(db_path, "approve", "--crash-after-decision-audit", env_extra=env)
    assert crashed.returncode == 91, crashed.stderr
    assert "decision audit committed; crashing" in crashed.stdout
    assert call_log_lines(call_log) == []  # backend not yet invoked
    types = event_types(db_path)
    assert types.count("decision:approve") == 1  # the row that did commit

    # Fresh process: await_approval is genuinely incomplete and re-runs
    # from its start, re-attempting the same decision audit write.
    state = inspect_state(db_path)
    assert state["next"] == ["await_approval"], state

    # H003 R2 scenario: the pending interrupt's resume value was already
    # stored by the checkpointer during the crashed attempt, so a plain
    # invoke(None) retry re-runs the node (and its audit write) without a
    # new Command — exactly the duplication hazard INSERT OR IGNORE absorbs.
    resumed = run_cli(db_path, "retry", env_extra=env)
    assert resumed.returncode == 0, resumed.stderr

    # Exactly one of every logical event despite the node re-execution.
    types = event_types(db_path)
    assert types.count("decision:approve") == 1
    assert types.count("executed") == 1
    assert types.count("proposal") == 1
    assert call_log_lines(call_log) == [{"service": "nginx"}]
    final = inspect_state(db_path)
    assert final["next"] == []
    assert final["values"]["agent_observation"] == "agent-resumed:executed"


# ---------------------------------------------------------------------------
# Property 5/11: audit completeness with correlation identity, in order.
# ---------------------------------------------------------------------------


def test_audit_log_orders_events_with_correlation_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "week15.sqlite"
    call_log = tmp_path / "service_calls.log"
    env = {"HITL_CALL_LOG": str(call_log)}

    assert run_cli(db_path, "start", "--host", "web01", env_extra=env).returncode == 0
    assert run_cli(db_path, "edit", "--service", "postgres", env_extra=env).returncode == 0
    assert run_cli(db_path, "approve", env_extra=env).returncode == 0

    rows = audit_rows(db_path)
    keys = [key for key, _ in rows]
    types = [event_type for _, event_type in rows]
    assert types == [
        "proposal",             # v1 proposed
        "decision:edit",        # human edits
        "proposal",             # v2 (edited) re-enters approval
        "decision:approve",     # human approves v2
        "executed",             # backend ran once, on the edited payload
    ]
    # Every key carries the thread correlation identity.
    assert all(key.startswith(f"{THREAD_ID}:") for key in keys)
    assert f"{THREAD_ID}:executed:v2" in keys  # executed the edited version
    assert f"{THREAD_ID}:executed:v1" not in keys  # never the superseded one


# ---------------------------------------------------------------------------
# Unknown thread handling (Week 14 convention).
# ---------------------------------------------------------------------------


def test_unknown_thread_cannot_be_inspected_or_resumed(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"

    inspected = run_cli(db_path, "inspect")
    assert inspected.returncode == 2
    assert f"Unknown thread: {THREAD_ID}" in inspected.stdout

    resumed = run_cli(db_path, "approve")
    assert resumed.returncode == 2
    assert f"Unknown thread: {THREAD_ID}" in resumed.stdout
