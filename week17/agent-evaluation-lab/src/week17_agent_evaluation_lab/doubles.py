"""Observer doubles and the recording fake MCP session.

Only the RAG and generation seams are doubles. The MCP transport
(``homelab.stdio_client`` / ``homelab.ClientSession``) is patched with a
recording fake so the **real** ``MockHomeLab.collect()`` runs unchanged.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

# Week 8's MockAdapter.get_health() payload (5 static sanitized rows; the
# hypervisor-esxi row is degraded). Kept as literals so the fake session is
# self-contained and never imports/spawns the real server.
DEFAULT_HEALTH = [
    {
        "id": "router-openwrt",
        "name": "Main Gateway Router",
        "status": "healthy",
        "latency_ms": 1.2,
        "last_check_timestamp": "2026-09-21T15:30:00Z",
        "details": "WAN connection stable, 0% packet loss",
    },
    {
        "id": "hypervisor-esxi",
        "name": "Primary ESXi Node",
        "status": "degraded",
        "latency_ms": 15.4,
        "last_check_timestamp": "2026-09-21T15:30:00Z",
        "details": "Datastore free space low (<10%), fans at high RPM",
    },
    {
        "id": "db-postgres",
        "name": "Production Postgres Cluster",
        "status": "healthy",
        "latency_ms": 3.1,
        "last_check_timestamp": "2026-09-21T15:30:00Z",
        "details": "Active connections 18/100, replication lag 0s",
    },
    {
        "id": "app-nginx",
        "name": "Edge Ingress Proxy",
        "status": "healthy",
        "latency_ms": 0.8,
        "last_check_timestamp": "2026-09-21T15:30:00Z",
        "details": "Upstream response 200 OK",
    },
    {
        "id": "app-transmission",
        "name": "Torrent Download Service",
        "status": "healthy",
        "latency_ms": 4.2,
        "last_check_timestamp": "2026-09-21T15:30:00Z",
        "details": "3 active torrent downloads, peer bandwidth normal",
    },
]


def _result(payload, *, is_error=False):
    return SimpleNamespace(
        isError=is_error,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
    )


class RecordingSession:
    """Fake ``ClientSession`` recording ``(name, arguments)`` call order."""

    def __init__(self, *, ping_payload=None, health_payload=None, ping_is_error=False):
        self.calls: list[tuple[str, dict]] = []
        self._ping = ping_payload if ping_payload is not None else {"adapter_mode": "mock", "read_only": True}
        self._health = health_payload if health_payload is not None else DEFAULT_HEALTH
        self._ping_is_error = ping_is_error

    async def initialize(self):
        return None

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "ping":
            return _result(self._ping, is_error=self._ping_is_error)
        if name == "get_health_status":
            return _result(self._health)
        raise AssertionError(f"unexpected tool {name!r}")


@asynccontextmanager
async def _fake_stdio(parameters):
    # Real collect() still builds the mock/read-only stdio parameters; we only
    # replace the transport so no process is spawned.
    assert parameters.env["HOMELAB_MODE"] == "mock"
    yield object(), object()


def patch_homelab_transport(session):
    """Context manager patching the MCP transport with ``session``'s fake."""
    return _patched(session)


class _patched:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        import homelab_knowledge_agent.homelab as homelab

        self._homelab = homelab
        self._prev_stdio = homelab.stdio_client
        self._prev_session = homelab.ClientSession

        @asynccontextmanager
        async def fake_session(*args):
            yield self._session

        homelab.stdio_client = _fake_stdio
        homelab.ClientSession = fake_session
        return self._session

    def __exit__(self, *exc):
        self._homelab.stdio_client = self._prev_stdio
        self._homelab.ClientSession = self._prev_session
        return False


class ScriptedRag:
    """Deterministic RAG double returning a record's inline fixture rows."""

    def __init__(self, record):
        self._rows = [
            {
                "source_path": row.source_path,
                "heading_path": row.heading_path,
                "content": row.content,
                "similarity": row.similarity,
            }
            for row in record.fixture.rag_rows
        ]
        self.calls: list[str] = []

    def retrieve(self, question):
        self.calls.append(question)
        return list(self._rows)


class ScriptedGeneration:
    """Deterministic quote-the-evidence generation double (never a model)."""

    def __init__(self, record, *, fail=False):
        self._record = record
        self._fail = fail
        self.calls: list[str] = []

    async def generate(self, prompt):
        self.calls.append(prompt)
        if self._fail:
            raise RuntimeError("scripted generation failure")
        rows = self._record.fixture.rag_rows
        head = rows[0]
        return (
            f"[deterministic template] {self._record.question} "
            f"Evidence: {head.content} ({head.source_path} — {head.heading_path}). "
            "MCP live data is mock adapter data for this request."
        )
