"""流式端点：SSE（异步）与 WebSocket（同步 TestClient）。"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient


async def test_sse_stream_emits_check_and_done(client: httpx.AsyncClient) -> None:
    response = await client.get("/events/checks")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: check" in text
    assert "event: done" in text
    assert '"name": "esxi-01"' in text


def test_websocket_check_success(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/checks") as websocket:
            websocket.send_text("openwrt-01")
            data = websocket.receive_json()

    assert data["host"]["name"] == "openwrt-01"
    assert data["status"] in {"up", "degraded", "down", "unknown"}


def test_websocket_unknown_host_returns_error(app: FastAPI) -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/checks") as websocket:
            websocket.send_text("ghost-01")
            data = websocket.receive_json()

    assert data["error"]["code"] == "host_not_found"
    assert data["error"]["hostname"] == "ghost-01"
