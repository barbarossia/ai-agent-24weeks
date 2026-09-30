from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langsmith import tracing_context

from persistence_checkpoint_lab.graph import build_graph, checkpoint_connection


DEFAULT_THREAD_ID = "week14-demo"
DEFAULT_DB = Path("data/week14.sqlite")


@contextmanager
def _open_graph(db_path: Path):
    with closing(checkpoint_connection(db_path)) as connection, tracing_context(enabled=False):
        yield build_graph(db_path, SqliteSaver(connection))


def _snapshot(db_path: Path, thread_id: str):
    with _open_graph(db_path) as graph:
        return graph.get_state({"configurable": {"thread_id": thread_id}})


def _effect_count(db_path: Path, thread_id: str) -> int:
    if not db_path.exists():
        return 0
    with closing(sqlite3.connect(db_path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mock_effects'"
        ).fetchone()
        if table is None:
            return 0
        row = connection.execute(
            "SELECT COUNT(*) FROM mock_effects WHERE idempotency_key = ?",
            (f"{thread_id}:step3:mock-notification",),
        ).fetchone()
        return int(row[0])


def _state_json(snapshot, effects: int) -> str:
    return json.dumps(
        {
            "values": snapshot.values,
            "next": list(snapshot.next),
            "step": snapshot.metadata.get("step") if snapshot.metadata else None,
            "mock_side_effect_count": effects,
        },
        indent=2,
        sort_keys=True,
    )


def run_start(db_path: Path, thread_id: str, crash_step3: bool) -> int:
    with _open_graph(db_path) as graph:
        graph.invoke(
            {"completed_steps": []},
            config={"configurable": {"thread_id": thread_id, "crash_step3": crash_step3}},
            durability="sync",
        )
    return 0


def run_inspect(db_path: Path, thread_id: str) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if not (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"):
        print(f"Unknown thread: {thread_id}")
        return 2
    print(_state_json(snapshot, _effect_count(db_path, thread_id)))
    return 0


def run_resume(db_path: Path, thread_id: str) -> int:
    snapshot = _snapshot(db_path, thread_id)
    if not (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"):
        print(f"Unknown thread: {thread_id}")
        return 2
    if not snapshot.next:
        print(f"Thread already complete: {thread_id}")
        print(_state_json(snapshot, _effect_count(db_path, thread_id)))
        return 0

    print(f"Resuming thread: {thread_id}", flush=True)
    with _open_graph(db_path) as graph:
        graph.invoke(None, config={"configurable": {"thread_id": thread_id}}, durability="sync")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph crash/restart checkpoint demo")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start the deterministic three-step thread")
    start.add_argument("--crash-step3", action="store_true", help="crash once after Step3's mock effect")
    commands.add_parser("inspect", help="read the latest persisted thread state")
    commands.add_parser("resume", help="resume an interrupted thread or report completion")

    args = parser.parse_args()
    if args.command == "start":
        raise SystemExit(run_start(args.db, args.thread_id, args.crash_step3))
    if args.command == "inspect":
        raise SystemExit(run_inspect(args.db, args.thread_id))
    if args.command == "resume":
        raise SystemExit(run_resume(args.db, args.thread_id))


if __name__ == "__main__":
    main()
