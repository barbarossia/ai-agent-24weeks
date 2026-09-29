import asyncio
import socket

import pytest


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline tests must not access networks, processes or databases")
    original_connect, original_pair = socket.socket.connect, socket.socketpair

    def local_event_loop_pair(*args, **kwargs):
        # Windows implements asyncio's self-pipe with a private loopback socket pair.
        # Permit only construction of that pair, not arbitrary application connections.
        with monkeypatch.context() as context:
            context.setattr(socket.socket, "connect", original_connect)
            return original_pair(*args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "socketpair", local_event_loop_pair)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", denied)
    import psycopg
    monkeypatch.setattr(psycopg, "connect", denied)
