"""Week 15 StateGraph: Agent Proposal -> Human Approval -> Execute.

Verified edge set (mirrors the corrected research design in H003):

    START -> propose -> await_approval
    await_approval -[approve]-> execute_write -> resume_agent -> END
    await_approval -[reject]-> rejected -> END
    await_approval -[edit]-> await_approval   (self-loop, re-interrupts)

* ``propose`` auto-executes Read Tools (no approval) and builds the Write
  Tool proposal (``restart_service``).
* ``await_approval`` is the only ``interrupt()`` call site. LangGraph
  re-executes an interrupted node from its start on resume, so this node
  performs **no** side effects before ``interrupt()`` returns; the decision
  audit row is written only after the resume value is in hand.
* ``execute_write`` is the **sole** caller of the mock ``restart_service``
  backend. The backend itself is transactional (H006-F1 correction): it
  claims the ``write_effects`` idempotency key and applies the mock
  restart in one SQLite commit, so a crash anywhere — before the backend
  transaction, during it, or between the effect commit and the node's
  checkpoint commit — cannot produce a second restart on retry.
* ``resume_agent`` folds the outcome into an agent-visible observation —
  the explicit "resumes the Agent flow" edge (H002 R5).
* ``rejected`` is a separate terminal node that never reaches
  ``execute_write`` or ``resume_agent``, structurally enforcing "rejection
  has no service side effect".

Crash hooks (test-only config flags, Week 14's ``os._exit`` technique):
``crash_after_decision_audit`` exits right after the decision audit row
commits but before ``await_approval`` returns its update (the H002 R2
hazard window); ``crash_after_effect`` exits right after the atomic
effect transaction and its audit row commit but before ``execute_write``
returns its update (the H002 R1 hazard window); ``crash_before_commit``
exits *inside* the backend transaction, after the restart mutation
statements run but before the transaction commits (the H006-F1 window),
proving the claim+mutation pair roll back together.
"""

from __future__ import annotations

import os
import sqlite3
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from human_in_the_loop_lab.audit import (
    audit_once,
    decision_key,
    executed_key,
    failed_key,
    proposal_key,
    rejected_key,
    write_effect_key,
)
from human_in_the_loop_lab.tools import (
    READ_TOOLS,
    ToolExecutionError,
    restart_service_from_env,
)

PROPOSAL_TOOL = "restart_service"


class ApprovalState(TypedDict, total=False):
    question: str
    host: str
    proposal: dict[str, Any] | None
    proposal_version: int
    decision_ordinal: int
    read_results: list[dict[str, Any]]
    decision: dict[str, Any] | None
    executed_result: dict[str, Any] | None
    execution_status: str | None
    execution_error: str | None
    agent_observation: str | None
    calls: Annotated[list[str], add]


def build_graph(
    db_path: Path,
    checkpointer: SqliteSaver,
    backend=None,
):
    """Compile the approval graph.

    ``backend`` overrides the mock ``restart_service`` backend for tests;
    it must accept ``(service, *, db_path, effect_key,
    crash_before_commit)`` and return ``(applied, result)`` like
    ``tools.restart_service``. The default backend is the transactional
    mock, which also appends applied restarts to the ``HITL_CALL_LOG``
    file when that variable is set, as evidence outside the machinery
    under test.
    """

    def propose(state: ApprovalState, config: RunnableConfig) -> dict[str, Any]:
        host = state["host"]
        # Read Tools auto-execute: no interrupt, no approval, side-effect free.
        read_results: list[dict[str, Any]] = []
        for name, tool in READ_TOOLS.items():
            try:
                result = tool["func"](host=host)
            except ToolExecutionError as error:
                result = {"host": host, "error": str(error)}
            read_results.append({"tool": name, "result": result})
        proposal = {"tool": PROPOSAL_TOOL, "args": {"service": "nginx"}, "host": host}
        thread_id = config["configurable"]["thread_id"]
        audit_once(
            db_path,
            proposal_key(thread_id, 1),
            thread_id,
            "proposal",
            {"tool": PROPOSAL_TOOL, "args": proposal["args"], "version": 1},
        )
        return {
            "read_results": read_results,
            "proposal": proposal,
            "proposal_version": 1,
            "decision_ordinal": 0,
            "calls": ["propose"],
        }

    def await_approval(state: ApprovalState, config: RunnableConfig) -> dict[str, Any]:
        version = state["proposal_version"]
        thread_id = config["configurable"]["thread_id"]
        # No side effects before interrupt(): this node re-runs from its
        # start on every resume. The resume value is the human decision.
        decision = interrupt(
            {
                "prompt": "Approve this Write Tool call?",
                "proposal": state["proposal"],
                "version": version,
            }
        )
        ordinal = state["decision_ordinal"] + 1
        audit_once(
            db_path,
            decision_key(thread_id, ordinal, decision["action"], version),
            thread_id,
            f"decision:{decision['action']}",
            {
                "action": decision["action"],
                "version": version,
                "edited_args": decision.get("proposal", {}).get("args"),
            },
        )
        if (
            config["configurable"].get("crash_after_decision_audit", False)
            and decision["action"] == "approve"
        ):
            print(
                "decision audit committed; crashing before node update (exit 91)",
                flush=True,
            )
            os._exit(91)
        if decision["action"] == "edit":
            edited = decision.get("proposal") or state["proposal"]
            next_version = version + 1
            audit_once(
                db_path,
                proposal_key(thread_id, next_version),
                thread_id,
                "proposal",
                {"tool": PROPOSAL_TOOL, "args": edited["args"], "version": next_version},
            )
            return {
                "decision": decision,
                "proposal": edited,
                "proposal_version": next_version,
                "decision_ordinal": ordinal,
                "calls": [f"review:{decision['action']}"],
            }
        return {
            "decision": decision,
            "decision_ordinal": ordinal,
            "calls": [f"review:{decision['action']}"],
        }

    def route_decision(state: ApprovalState) -> str:
        action = state["decision"]["action"]
        if action == "approve":
            return "execute_write"
        if action == "reject":
            return "rejected"
        if action == "edit":
            return "await_approval"
        raise ValueError(f"unknown decision action: {action!r}")

    def execute_write(state: ApprovalState, config: RunnableConfig) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        version = state["proposal_version"]
        proposal = state["proposal"]
        service = proposal["args"]["service"]
        effect_key = write_effect_key(thread_id, version)
        crash_before_commit = config["configurable"].get("crash_before_commit", False)
        runner = backend or restart_service_from_env
        try:
            # Atomic mock transaction: claim effect_key AND apply the mock
            # restart (or return the recorded outcome) in one commit.
            applied, outcome = runner(
                service,
                db_path=db_path,
                effect_key=effect_key,
                crash_before_commit=crash_before_commit,
            )
        except ToolExecutionError as error:
            audit_once(
                db_path,
                failed_key(thread_id, version),
                thread_id,
                "execution_failed",
                {"service": service, "version": version, "error": str(error)},
            )
            return {
                "execution_status": "failed",
                "execution_error": str(error),
                "calls": ["execute:failed"],
            }
        audit_once(
            db_path,
            executed_key(thread_id, version),
            thread_id,
            "executed",
            {
                "service": service,
                "version": version,
                "result": outcome,
                "replay": not applied,
            },
        )
        if applied and config["configurable"].get("crash_after_effect", False):
            print(
                "write effect committed; crashing before node update (exit 92)",
                flush=True,
            )
            os._exit(92)
        return {
            "executed_result": outcome,
            "execution_status": "executed",
            "calls": ["execute:replayed" if not applied else f"execute:{service}"],
        }

    def resume_agent(state: ApprovalState) -> dict[str, Any]:
        status = state["execution_status"]
        return {
            "agent_observation": f"agent-resumed:{status}",
            "calls": [f"agent-resumed:{status}"],
        }

    def rejected(state: ApprovalState, config: RunnableConfig) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        audit_once(
            db_path,
            rejected_key(thread_id, state["proposal_version"]),
            thread_id,
            "rejected",
            {"version": state["proposal_version"], "args": state["proposal"]["args"]},
        )
        return {
            "agent_observation": "agent-resumed:rejected",
            "calls": ["rejected-end"],
        }

    builder = StateGraph(ApprovalState)
    builder.add_node("propose", propose)
    builder.add_node("await_approval", await_approval)
    builder.add_node("execute_write", execute_write)
    builder.add_node("resume_agent", resume_agent)
    builder.add_node("rejected", rejected)
    builder.add_edge(START, "propose")
    builder.add_edge("propose", "await_approval")
    builder.add_conditional_edges(
        "await_approval",
        route_decision,
        {
            "execute_write": "execute_write",
            "rejected": "rejected",
            "await_approval": "await_approval",
        },
    )
    builder.add_edge("execute_write", "resume_agent")
    builder.add_edge("resume_agent", END)
    builder.add_edge("rejected", END)
    return builder.compile(checkpointer=checkpointer)


def checkpoint_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.execute("PRAGMA synchronous=FULL")
    return connection


__all__ = ["build_graph", "checkpoint_connection", "ApprovalState", "PROPOSAL_TOOL"]
