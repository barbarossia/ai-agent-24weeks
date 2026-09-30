from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


class LabState(TypedDict, total=False):
    completed_steps: list[str]
    message: str


def _record_mock_side_effect(db_path: Path, idempotency_key: str) -> bool:
    """Commit one mock effect per key; return True only for its first commit."""
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS mock_effects (
                   idempotency_key TEXT PRIMARY KEY,
                   effect TEXT NOT NULL
               )"""
        )
        cursor = connection.execute(
            "INSERT OR IGNORE INTO mock_effects(idempotency_key, effect) VALUES (?, ?)",
            (idempotency_key, "step3:mock-notification-sent"),
        )
        connection.commit()
        return cursor.rowcount == 1


def build_graph(db_path: Path, checkpointer: SqliteSaver):
    def step1(state: LabState) -> dict[str, object]:
        print("Step1 ✓", flush=True)
        return {"completed_steps": [*state.get("completed_steps", []), "Step1"]}

    def step2(state: LabState) -> dict[str, object]:
        print("Step2 ✓", flush=True)
        return {"completed_steps": [*state.get("completed_steps", []), "Step2"]}

    def step3(state: LabState, config: RunnableConfig) -> dict[str, object]:
        thread_id = config["configurable"]["thread_id"]
        idempotency_key = f"{thread_id}:step3:mock-notification"
        created = _record_mock_side_effect(db_path, idempotency_key)
        status = "created" if created else "already recorded"
        print(f"Step3 side effect: {status} ({idempotency_key})", flush=True)

        if created and config["configurable"].get("crash_step3", False):
            print("Step3 crash before graph update (exit 86)", flush=True)
            os._exit(86)

        print("Step3 ✓", flush=True)
        return {"completed_steps": [*state.get("completed_steps", []), "Step3"]}

    builder = StateGraph(LabState)
    builder.add_node("step1", step1)
    builder.add_node("step2", step2)
    builder.add_node("step3", step3)
    builder.add_edge(START, "step1")
    builder.add_edge("step1", "step2")
    builder.add_edge("step2", "step3")
    builder.add_edge("step3", END)
    return builder.compile(checkpointer=checkpointer)


def checkpoint_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.execute("PRAGMA synchronous=FULL")
    return connection
