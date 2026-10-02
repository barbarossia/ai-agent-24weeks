"""Week 15 CLI: start / inspect / approve / reject / edit / audit.

Each subcommand opens its own SQLite connection and exits (Week 14
style), which is what makes "approval happens in a separate step, in a
separate process" observable and testable across process boundaries.

All invocations disable LangSmith tracing, matching Weeks 13–14. Crash
flags mirror Week 14's ``--crash-step3``: they terminate the process via
``os._exit`` after a durable commit but before the node's graph update is
checkpointed, simulating the hazardous windows the audit/idempotency
design must survive.
"""

from __future__ import annotations

import argparse
import json
from contextlib import closing, contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from langsmith import tracing_context

from human_in_the_loop_lab.audit import read_audit
from human_in_the_loop_lab.graph import build_graph, checkpoint_connection

DEFAULT_THREAD_ID = "week15-demo"
DEFAULT_DB = Path("data/week15.sqlite")


@contextmanager
def _open_graph(db_path: Path, **configurable):
    with closing(checkpoint_connection(db_path)) as connection, tracing_context(enabled=False):
        yield build_graph(db_path, SqliteSaver(connection))


def _config(thread_id: str, **extra) -> dict:
    return {"configurable": {"thread_id": thread_id, **extra}}


def _snapshot(db_path: Path, thread_id: str):
    with _open_graph(db_path) as graph:
        return graph.get_state(_config(thread_id))


def _pending_proposal(snapshot) -> dict | None:
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    for entry in interrupts:
        value = getattr(entry, "value", None)
        if isinstance(value, dict) and "proposal" in value:
            return value
    return None


def run_start(db_path: Path, thread_id: str, host: str, crash_after_effect: bool) -> int:
    with _open_graph(db_path) as graph:
        result = graph.invoke(
            {"question": f"diagnose {host}", "host": host},
            config=_config(thread_id, crash_after_effect=crash_after_effect),
            durability="sync",
        )
    interrupts = result.get("__interrupt__", ())
    printed = False
    for entry in interrupts:
        value = getattr(entry, "value", None)
        if isinstance(value, dict) and "proposal" in value:
            print("PENDING APPROVAL")
            print(json.dumps(value, indent=2, sort_keys=True))
            printed = True
    if not printed and not interrupts:
        print(json.dumps(
            {k: v for k, v in result.items() if k != "__interrupt__"},
            indent=2, sort_keys=True, default=str))
    return 0


def run_inspect(db_path: Path, thread_id: str) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if not (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"):
        print(f"Unknown thread: {thread_id}")
        return 2
    pending = _pending_proposal(snapshot)
    payload = {
        "values": {
            key: value
            for key, value in snapshot.values.items()
            if key in ("host", "proposal", "proposal_version", "decision",
                       "execution_status", "agent_observation", "calls")
        },
        "next": list(snapshot.next),
        "pending_proposal": pending,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _resume(db_path: Path, thread_id: str, resume_value: dict, **flags) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if not (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"):
        print(f"Unknown thread: {thread_id}")
        return 2
    if not snapshot.next:
        print(f"Thread already complete: {thread_id}")
        print(json.dumps(
            {key: value for key, value in snapshot.values.items()
             if key in ("agent_observation", "execution_status", "calls")},
            indent=2, sort_keys=True, default=str))
        return 0
    with _open_graph(db_path) as graph:
        result = graph.invoke(
            Command(resume=resume_value),
            config=_config(thread_id, **flags),
            durability="sync",
        )
    calls = result.get("calls", [])
    print(json.dumps(
        {
            "calls": calls,
            "execution_status": result.get("execution_status"),
            "agent_observation": result.get("agent_observation"),
        },
        indent=2, sort_keys=True, default=str))
    return 0


def run_approve(
    db_path: Path,
    thread_id: str,
    crash_after_decision_audit: bool,
    crash_after_effect: bool,
    crash_before_commit: bool,
) -> int:
    return _resume(
        db_path,
        thread_id,
        {"action": "approve"},
        crash_after_decision_audit=crash_after_decision_audit,
        crash_after_effect=crash_after_effect,
        crash_before_commit=crash_before_commit,
    )


def run_reject(db_path: Path, thread_id: str) -> int:
    return _resume(db_path, thread_id, {"action": "reject"})


def run_retry(db_path: Path, thread_id: str) -> int:
    """Plain ``invoke(None)`` retry for a thread interrupted mid-node.

    Unlike approve/reject/edit, this sends no new resume value: the stored
    decision (if any) is replayed by the checkpointer. This is the Week 14
    recovery path, used to retry after a simulated crash between a durable
    commit (write effect or audit row) and the owning node's checkpoint.
    """
    snapshot = _snapshot(db_path, thread_id)
    if not (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"):
        print(f"Unknown thread: {thread_id}")
        return 2
    if not snapshot.next:
        print(f"Thread already complete: {thread_id}")
        print(json.dumps(
            {key: value for key, value in snapshot.values.items()
             if key in ("agent_observation", "execution_status", "calls")},
            indent=2, sort_keys=True, default=str))
        return 0
    with _open_graph(db_path) as graph:
        result = graph.invoke(None, config=_config(thread_id), durability="sync")
    print(json.dumps(
        {
            "calls": result.get("calls", []),
            "execution_status": result.get("execution_status"),
            "agent_observation": result.get("agent_observation"),
        },
        indent=2, sort_keys=True, default=str))
    return 0


def run_edit(db_path: Path, thread_id: str, service: str) -> int:
    snapshot = _snapshot(db_path, thread_id)
    pending = _pending_proposal(snapshot)
    if pending is None:
        print(f"No pending proposal for thread: {thread_id}")
        return 3
    edited = dict(pending["proposal"])
    edited["args"] = {"service": service}
    return _resume(db_path, thread_id, {"action": "edit", "proposal": edited})


def run_audit(db_path: Path, thread_id: str | None) -> int:
    events = read_audit(db_path, thread_id)
    print(json.dumps(
        [
            {
                "event_key": event.event_key,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in events
        ],
        indent=2, sort_keys=True))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Week 15 human-in-the-loop Write Tool approval demo")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser(
        "start", help="run Read Tools, propose the Write Tool call, pause for approval")
    start.add_argument("--host", default="web01")
    start.add_argument("--crash-after-effect", action="store_true",
                       help="crash once after the write effect commits, before the node update")
    commands.add_parser("inspect", help="show thread state and any pending proposal")
    approve = commands.add_parser("approve", help="resume with an approve decision")
    approve.add_argument("--crash-after-decision-audit", action="store_true",
                         help="crash once after the decision audit commit, before the node update")
    approve.add_argument("--crash-after-effect", action="store_true",
                         help="crash once after the effect transaction commits, before the node update")
    approve.add_argument("--crash-before-commit", action="store_true",
                         help="crash inside the backend transaction before it commits (rolls back atomically)")
    commands.add_parser("reject", help="resume with a reject decision")
    commands.add_parser("retry", help="plain resume after a mid-node crash (no new decision)")
    edit = commands.add_parser("edit", help="resume with an edited proposal (re-enters approval)")
    edit.add_argument("--service", required=True, help="edited service name")
    audit = commands.add_parser("audit", help="print the audit log")
    audit.add_argument("--all", action="store_true", help="include all threads")

    args = parser.parse_args()
    if args.command == "start":
        raise SystemExit(
            run_start(args.db, args.thread_id, args.host, args.crash_after_effect))
    if args.command == "inspect":
        raise SystemExit(run_inspect(args.db, args.thread_id))
    if args.command == "approve":
        raise SystemExit(
            run_approve(args.db, args.thread_id,
                        args.crash_after_decision_audit, args.crash_after_effect,
                        args.crash_before_commit))
    if args.command == "reject":
        raise SystemExit(run_reject(args.db, args.thread_id))
    if args.command == "retry":
        raise SystemExit(run_retry(args.db, args.thread_id))
    if args.command == "edit":
        raise SystemExit(run_edit(args.db, args.thread_id, args.service))
    if args.command == "audit":
        raise SystemExit(run_audit(args.db, None if args.all else args.thread_id))


if __name__ == "__main__":
    main()
