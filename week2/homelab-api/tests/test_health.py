"""``GET /health`` 与根路径。"""

from __future__ import annotations

import httpx


async def test_health_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "homelab-api",
        "version": "0.1.0",
        "week": 2,
    }


async def test_root_index_points_to_docs(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["docs"] == "/docs"
    assert body["week"] == 2
