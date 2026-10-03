from __future__ import annotations

import argparse
import json
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from langsmith import tracing_context

from .workflow import (CHECKS, MockBackends, build_graph, cancellation_record,
                       checkpoint_connection, clear_cancel, init_control_table,
                       request_cancel)

DEFAULT_DB = Path("data/week16.sqlite")
DEFAULT_THREAD_ID = "week16-demo"
FAULT_OPTIONS = [f"{mode}:{name}" for mode in ("transient", "exhaust", "fail") for name in CHECKS]


@contextmanager
def _open_graph(db_path: Path, backends: MockBackends | None = None):
    init_control_table(db_path)
    with closing(checkpoint_connection(db_path)) as connection, tracing_context(enabled=False):
        yield build_graph(db_path, SqliteSaver(connection), backends=backends)


def _config(thread_id: str, **extra: Any) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, **extra}}


def _snapshot(db_path: Path, thread_id: str):
    with _open_graph(db_path) as graph:
        return graph.get_state(_config(thread_id))


def _known(snapshot) -> bool:
    return bool((snapshot.config or {}).get("configurable", {}).get("checkpoint_id"))


def _pending_approval(snapshot) -> dict[str, Any] | None:
    for entry in getattr(snapshot, "interrupts", ()) or ():
        value = getattr(entry, "value", None)
        if isinstance(value, dict) and "proposal" in value:
            return value
    return None


def run_start(db_path: Path, thread_id: str, host: str, faults: list[str]) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if _known(snapshot):
        print(f"Thread already exists: {thread_id}")
        return 3
    fault_map = {entry.split(":", 1)[1]: entry.split(":", 1)[0] for entry in faults}
    with _open_graph(db_path) as graph:
        result = graph.invoke({"host": host, "retry_nonce": 0, "mock_faults": fault_map},
                              config=_config(thread_id), durability="sync")
    interruption = result.get("__interrupt__", ())
    if interruption:
        pending = next((item.value for item in interruption
                        if isinstance(getattr(item, "value", None), dict)), None)
        print("PENDING APPROVAL")
        print(json.dumps(pending, indent=2, sort_keys=True))
    else:
        print(json.dumps({key: result.get(key) for key in
                          ("run_status", "cancel_observed_at", *[f"{n}_result" for n in CHECKS])},
                         indent=2))
    return 0


def run_inspect(db_path: Path, thread_id: str) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if not _known(snapshot):
        print(f"Unknown thread: {thread_id}")
        return 2
    values = snapshot.values
    payload = {
        "thread_id": thread_id,
        "run_status": values.get("run_status"),
        "cancel_requested": cancellation_record(db_path, thread_id),
        "cancel_observed_at": values.get("cancel_observed_at"),
        "checks": {name: values.get(f"{name}_result", {"status": "absent"})
                   for name in CHECKS},
        "values": {key: values[key] for key in
                   ("host", "analysis", "proposal", "proposal_version", "decision",
                    "execution_status", "execution_result", "agent_observation", "retry_nonce")
                   if key in values},
        "next": list(snapshot.next),
        "pending_approval": _pending_approval(snapshot),
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def run_cancel(db_path: Path, thread_id: str, reason: str | None) -> int:
    request_cancel(db_path, thread_id, reason)
    print(json.dumps({"thread_id": thread_id, "cancel_requested": True, "reason": reason},
                     indent=2, sort_keys=True))
    return 0


def run_retry(db_path: Path, thread_id: str, faults: list[str]) -> int:
    clear_cancel(db_path, thread_id)
    snapshot = _snapshot(db_path, thread_id)
    if not _known(snapshot):
        print(f"Unknown thread: {thread_id}")
        return 2
    if snapshot.next:
        payload: Any = None
    else:
        payload = {"retry_nonce": int(snapshot.values.get("retry_nonce", 0)) + 1}
    if faults:
        payload = dict(payload or {})
        payload["mock_faults"] = {
            entry.split(":", 1)[1]: entry.split(":", 1)[0] for entry in faults
        }
    with _open_graph(db_path) as graph:
        result = graph.invoke(payload, config=_config(thread_id), durability="sync")
    if result.get("__interrupt__"):
        print("PENDING APPROVAL")
        print(json.dumps({"thread_id": thread_id, "run_status": result.get("run_status")},
                         indent=2, sort_keys=True))
    else:
        print(json.dumps({"thread_id": thread_id, "run_status": result.get("run_status"),
                          "retry_nonce": result.get("retry_nonce")}, indent=2, sort_keys=True))
    return 0


def _resume(db_path: Path, thread_id: str, action: str) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if not _known(snapshot):
        print(f"Unknown thread: {thread_id}")
        return 2
    if not snapshot.next:
        print(f"Thread already complete: {thread_id}")
        return 0
    if "await_approval" not in snapshot.next:
        print(f"Thread is not awaiting approval: {thread_id}")
        return 3
    with _open_graph(db_path) as graph:
        result = graph.invoke(Command(resume={"action": action}),
                              config=_config(thread_id), durability="sync")
    print(json.dumps({"thread_id": thread_id, "run_status": result.get("run_status"),
                      "execution_status": result.get("execution_status"),
                      "agent_observation": result.get("agent_observation")},
                     indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Week 16 durable mock diagnosis workflow")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="run checks and pause before the proposed fix")
    start.add_argument("--host", default="lab.example")
    start.add_argument("--fault", action="append", choices=FAULT_OPTIONS, default=[])
    commands.add_parser("inspect", help="show cancellation and each per-check outcome")
    cancel = commands.add_parser("cancel", help="persist a cooperative cancellation request")
    cancel.add_argument("--reason", default="user-request")
    retry = commands.add_parser("retry", help="clear cancellation and retry only non-ok checks")
    retry.add_argument("--fault", action="append", choices=FAULT_OPTIONS, default=[])
    commands.add_parser("approve", help="resume approval and invoke the replay-safe mock fix")
    commands.add_parser("reject", help="reject the proposal without invoking the mock fix")
    args = parser.parse_args()
    if args.command == "start":
        return run_start(args.db, args.thread_id, args.host, args.fault)
    if args.command == "inspect":
        return run_inspect(args.db, args.thread_id)
    if args.command == "cancel":
        return run_cancel(args.db, args.thread_id, args.reason)
    if args.command == "retry":
        return run_retry(args.db, args.thread_id, args.fault)
    if args.command in ("approve", "reject"):
        return _resume(args.db, args.thread_id, args.command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
