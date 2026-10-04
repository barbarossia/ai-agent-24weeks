"""Week 17 offline test isolation.

Clones Week 12's ``offline_only`` guards verbatim (socket connect /
create_connection, asyncio.create_subprocess_exec, psycopg.connect) with **no
per-test lifts and no markers**. The fake MCP transport replaces Week 12's
transport before any process or socket exists, so no guard needs weakening.
"""

import asyncio
import socket
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = LAB_ROOT / "data" / "golden_eval.jsonl"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline tests must not access networks, processes or databases")

    original_connect, original_pair = socket.socket.connect, socket.socketpair

    def local_event_loop_pair(*args, **kwargs):
        # Windows implements asyncio's self-pipe with a private loopback socket
        # pair. Permit only construction of that pair, not application connects.
        with monkeypatch.context() as context:
            context.setattr(socket.socket, "connect", original_connect)
            return original_pair(*args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "socketpair", local_event_loop_pair)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", denied)
    import psycopg

    monkeypatch.setattr(psycopg, "connect", denied)


@pytest.fixture(scope="session")
def dataset_path():
    return DATASET_PATH


@pytest.fixture
def records():
    from week17_agent_evaluation_lab.dataset import load_dataset

    return load_dataset(DATASET_PATH)
