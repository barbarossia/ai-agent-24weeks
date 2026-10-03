from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import Counter
from contextlib import closing
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

CHECKS = ("dns", "service", "connectivity", "logs")
MAX_ATTEMPTS = 2


class CheckOutcome(TypedDict):
    status: str
    detail: str
    attempts: int


class WorkflowState(TypedDict, total=False):
    host: str
    retry_nonce: int
    mock_faults: dict[str, str]
    dns_result: CheckOutcome
    service_result: CheckOutcome
    connectivity_result: CheckOutcome
    logs_result: CheckOutcome
    cancel_observed_at: str | None
    run_status: str
    events: Annotated[list[dict[str, Any]], add]
    analysis: dict[str, Any]
    proposal: dict[str, Any]
    proposal_version: int
    decision: dict[str, Any]
    execution_status: str
    execution_result: dict[str, Any]
    agent_observation: str


class TransientCheckError(Exception):
    pass


class PermanentCheckError(Exception):
    pass


class MockBackends:
    """Deterministic, thread-safe mock checks; never opens network sockets."""

    def __init__(self, gate: threading.Event | None = None,
                 entered: threading.Barrier | None = None) -> None:
        self._lock = threading.Lock()
        self._attempts: Counter[str] = Counter()
        self._threads: dict[str, set[str]] = {name: set() for name in CHECKS}
        self._active = 0
        self.max_overlap = 0
        self.join_runs = 0
        self.gate = gate
        self.entered = entered

    def check(self, name: str, host: str, attempt: int,
              faults: dict[str, str]) -> str:
        with self._lock:
            self._attempts[name] += 1
            self._threads[name].add(threading.current_thread().name)
            self._active += 1
            self.max_overlap = max(self.max_overlap, self._active)
        try:
            if self.entered is not None:
                self.entered.wait(timeout=10)
            if self.gate is not None and not self.gate.wait(timeout=10):
                raise TimeoutError("test synchronization gate timed out")
            mode = faults.get(name, "ok")
            if mode == "transient" and attempt == 1:
                raise TransientCheckError(f"{name} transient mock failure")
            if mode == "exhaust":
                raise TransientCheckError(f"{name} exhausted transient mock failure")
            if mode == "fail":
                raise PermanentCheckError(f"{name} scripted mock failure")
            return f"{name} mock check passed for {host}"
        finally:
            with self._lock:
                self._active -= 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "attempts": dict(self._attempts),
                "threads": {key: sorted(value) for key, value in self._threads.items()},
                "distinct_threads": len(set().union(*self._threads.values())),
                "max_overlap": self.max_overlap,
                "join_runs": self.join_runs,
            }


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def init_control_table(db_path: Path) -> None:
    with closing(_connect(db_path)) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS cancellation (
                   thread_id TEXT PRIMARY KEY,
                   requested_at TEXT NOT NULL DEFAULT (datetime('now')),
                   reason TEXT
               )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS mock_fix_effects (
                   thread_id TEXT PRIMARY KEY,
                   host TEXT NOT NULL,
                   result_json TEXT NOT NULL
               )"""
        )
        connection.commit()


def cancellation_record(db_path: Path, thread_id: str) -> dict[str, str] | None:
    init_control_table(db_path)
    with closing(_connect(db_path)) as connection:
        row = connection.execute(
            "SELECT requested_at, reason FROM cancellation WHERE thread_id=?", (thread_id,)
        ).fetchone()
    if row is None:
        return None
    return {"requested_at": row[0], "reason": row[1] or ""}


def request_cancel(db_path: Path, thread_id: str, reason: str | None) -> None:
    init_control_table(db_path)
    with closing(_connect(db_path)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO cancellation(thread_id, requested_at, reason) "
            "VALUES (?, datetime('now'), ?)", (thread_id, reason)
        )
        connection.commit()


def clear_cancel(db_path: Path, thread_id: str) -> None:
    init_control_table(db_path)
    with closing(_connect(db_path)) as connection:
        connection.execute("DELETE FROM cancellation WHERE thread_id=?", (thread_id,))
        connection.commit()


def checkpoint_connection(db_path: Path) -> sqlite3.Connection:
    connection = _connect(db_path)
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def _result_key(name: str) -> str:
    return f"{name}_result"


def _cancelled() -> CheckOutcome:
    return {"status": "cancelled", "detail": "not_run", "attempts": 0}


def build_graph(db_path: Path, checkpointer: SqliteSaver,
                backends: MockBackends | None = None):
    adapters = backends or MockBackends()
    init_control_table(db_path)

    def prepare(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        current = {name: state.get(_result_key(name)) for name in CHECKS}
        if cancellation_record(db_path, thread_id):
            updates = {_result_key(name): _cancelled()
                       for name in CHECKS if current[name] is None or current[name]["status"] != "ok"}
            updates.update({"cancel_observed_at": "pre_dispatch",
                            "run_status": "cancelled_before_dispatch",
                            "events": [{"event": "cancel_observed", "boundary": "pre_dispatch"}]})
            return updates
        return {"cancel_observed_at": None, "run_status": "diagnosing",
                "events": [{"event": "dispatch_prepared"}]}

    def dispatch(state: WorkflowState) -> list[str]:
        if state.get("cancel_observed_at") == "pre_dispatch":
            return ["cancelled"]
        return [name for name in CHECKS
                if (state.get(_result_key(name)) or {}).get("status") != "ok"] or ["join"]

    def make_check(name: str):
        def run(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
            faults = state.get("mock_faults", {})
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    detail = adapters.check(name, state["host"], attempt, faults)
                    outcome: CheckOutcome = {"status": "ok", "detail": detail,
                                             "attempts": attempt}
                    break
                except TransientCheckError as error:
                    if attempt == MAX_ATTEMPTS:
                        outcome = {"status": "failed", "detail": str(error),
                                   "attempts": attempt}
                except Exception as error:
                    outcome = {"status": "failed", "detail": str(error),
                               "attempts": attempt}
                    break
            return {_result_key(name): outcome,
                    "events": [{"event": "check_finished", "check": name,
                                "status": outcome["status"], "attempts": outcome["attempts"]}]}
        return run

    def join(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
        with adapters._lock:
            adapters.join_runs += 1
        thread_id = config["configurable"]["thread_id"]
        if cancellation_record(db_path, thread_id):
            return {"cancel_observed_at": "join",
                    "run_status": "cancelled_after_diagnostics",
                    "events": [{"event": "cancel_observed", "boundary": "join"}]}
        return {"run_status": "diagnostics_complete",
                "events": [{"event": "checks_joined"}]}

    def route_after_join(state: WorkflowState) -> str:
        return END if state.get("cancel_observed_at") == "join" else "analysis"

    def analysis(state: WorkflowState) -> dict[str, Any]:
        results = {name: state.get(_result_key(name), {"status": "absent"}) for name in CHECKS}
        return {"analysis": {"host": state["host"], "checks": results,
                             "failed_checks": [n for n in CHECKS
                                               if results[n]["status"] == "failed"]},
                "events": [{"event": "analysis_complete"}]}

    def propose(state: WorkflowState) -> dict[str, Any]:
        proposal = {"action": "review_diagnosis", "host": state["host"],
                    "failed_checks": state["analysis"]["failed_checks"]}
        return {"proposal": proposal, "proposal_version": 1,
                "run_status": "awaiting_approval",
                "events": [{"event": "proposal_created"}]}

    def await_approval(state: WorkflowState) -> dict[str, Any]:
        decision = interrupt({"prompt": "Approve the mock proposed fix?",
                              "proposal": state["proposal"], "version": state["proposal_version"]})
        action = decision.get("action") if isinstance(decision, dict) else None
        if action not in ("approve", "reject"):
            raise ValueError("approval decision must be approve or reject")
        return {"decision": {"action": action}, "events": [{"event": f"decision_{action}"}]}

    def route_decision(state: WorkflowState) -> str:
        return "execute_fix" if state["decision"]["action"] == "approve" else "rejected"

    def execute_fix(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        host = state["host"]
        result = {"status": "mock_applied", "host": host}
        with closing(_connect(db_path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "INSERT OR IGNORE INTO mock_fix_effects(thread_id, host, result_json) VALUES (?, ?, ?)",
                (thread_id, host, json.dumps(result, sort_keys=True)),
            )
            connection.commit()
            applied = cursor.rowcount == 1
            saved = connection.execute(
                "SELECT result_json FROM mock_fix_effects WHERE thread_id=?", (thread_id,)
            ).fetchone()[0]
        if applied:
            log_path = os.environ.get("W16_FIX_CALL_LOG")
            if log_path:
                path = Path(log_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"thread_id": thread_id, "host": host}) + "\n")
        return {"execution_status": "executed", "execution_result": json.loads(saved),
                "run_status": "completed", "events": [{"event": "mock_fix_applied" if applied
                                                            else "mock_fix_replayed"}]}

    def rejected(state: WorkflowState) -> dict[str, Any]:
        return {"execution_status": "rejected", "run_status": "rejected",
                "agent_observation": "agent-resumed:rejected",
                "events": [{"event": "fix_rejected"}]}

    def resumed(state: WorkflowState) -> dict[str, Any]:
        return {"agent_observation": "agent-resumed:executed"}

    builder = StateGraph(WorkflowState)
    builder.add_node("prepare", prepare)
    for name in CHECKS:
        builder.add_node(name, make_check(name))
        builder.add_edge(name, "join")
    builder.add_node("join", join)
    builder.add_node("analysis", analysis)
    builder.add_node("propose", propose)
    builder.add_node("await_approval", await_approval)
    builder.add_node("execute_fix", execute_fix)
    builder.add_node("rejected", rejected)
    builder.add_node("resumed", resumed)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", dispatch,
                                  {**{name: name for name in CHECKS}, "join": "join",
                                   "cancelled": END})
    builder.add_conditional_edges("join", route_after_join,
                                  {"analysis": "analysis", END: END})
    builder.add_edge("analysis", "propose")
    builder.add_edge("propose", "await_approval")
    builder.add_conditional_edges("await_approval", route_decision,
                                  {"execute_fix": "execute_fix", "rejected": "rejected"})
    builder.add_edge("execute_fix", "resumed")
    builder.add_edge("resumed", END)
    builder.add_edge("rejected", END)
    return builder.compile(checkpointer=checkpointer)


__all__ = ["CHECKS", "MAX_ATTEMPTS", "MockBackends", "WorkflowState", "build_graph",
           "checkpoint_connection", "cancellation_record", "request_cancel", "clear_cancel",
           "init_control_table"]
