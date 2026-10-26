from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .scenarios import get_scenario
from .telemetry import TraceRecorder
from .workflow import build_graph, initial_state


ApprovalProvider = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class WorkflowRun:
    thread_id: str
    state: dict[str, Any]
    pending_approval: dict[str, Any] | None


def new_thread_id() -> str:
    return f"demo_{uuid.uuid4().hex}"


def _interrupt_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    pending = state.get("__interrupt__", ())
    if not pending:
        return None
    first = pending[0]
    value = getattr(first, "value", None)
    return value if isinstance(value, dict) else None


def approval_reply(payload: dict[str, Any], choice: str, approver: str) -> dict[str, str]:
    if choice not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    if not approver or len(approver) > 80:
        raise ValueError("approver label must be between 1 and 80 characters")
    return {
        "decision": choice,
        "action_id": payload["action_id"],
        "proposal_digest": payload["proposal_digest"],
        "approver": approver,
    }


async def run_new_workflow(
    *,
    request: str,
    case_id: str,
    thread_id: str,
    vault_root: Path,
    checkpoint_path: Path,
    telemetry_dir: Path,
    approval_provider: ApprovalProvider | None = None,
) -> WorkflowRun:
    scenario = get_scenario(case_id)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    recorder = TraceRecorder(thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer, vault_root=vault_root, telemetry=recorder)
        try:
            state = await graph.ainvoke(initial_state(request, scenario, thread_id), config=config)
            payload = _interrupt_payload(state)
            if payload and approval_provider:
                decision = approval_provider(payload)
                if inspect.isawaitable(decision):
                    decision = await decision
                if decision is not None:
                    state = await graph.ainvoke(Command(resume=decision), config=config)
            pending = _interrupt_payload(state)
            outcome = "paused" if pending else (
                "recovered" if state.get("recovered") else (
                    "rejected" if state.get("approval", {}).get("decision") == "reject" else "unresolved"
                )
            )
            recorder.increment("workflow_runs_total", outcome=outcome)
            return WorkflowRun(thread_id=thread_id, state=state, pending_approval=pending)
        finally:
            recorder.write(telemetry_dir)


async def resume_workflow(
    *,
    thread_id: str,
    decision: str,
    approver: str,
    vault_root: Path,
    checkpoint_path: Path,
    telemetry_dir: Path,
) -> WorkflowRun:
    if not thread_id or len(thread_id) > 100:
        raise ValueError("invalid thread id")
    recorder = TraceRecorder.restore(telemetry_dir, thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer, vault_root=vault_root, telemetry=recorder)
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            raise ValueError("no pending checkpoint for this thread")
        values = snapshot.values
        proposal = values.get("proposal")
        if not proposal:
            raise ValueError("checkpoint has no pending remediation proposal")
        payload = {
            "action_id": proposal["action_id"],
            "proposal_digest": proposal["proposal_digest"],
        }
        reply = approval_reply(payload, decision, approver)
        try:
            state = await graph.ainvoke(Command(resume=reply), config=config)
            outcome = "recovered" if state.get("recovered") else (
                "rejected" if state.get("approval", {}).get("decision") == "reject" else "unresolved"
            )
            recorder.increment("workflow_runs_total", outcome=outcome)
            return WorkflowRun(
                thread_id=thread_id,
                state=state,
                pending_approval=_interrupt_payload(state),
            )
        finally:
            recorder.write(telemetry_dir)
