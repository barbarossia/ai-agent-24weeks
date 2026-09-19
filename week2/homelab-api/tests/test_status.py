"""分类状态路由：成功路径、空结果边界、探针失败 503。"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from ai_agent_lab.models import Host, Inventory
from homelab_api.deps import get_inventory, get_probe


async def test_docker_status_success(client: httpx.AsyncClient) -> None:
    response = await client.get("/docker/status")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "docker"
    assert body["results"]
    assert {item["host"]["kind"] for item in body["results"]} == {"docker"}
    assert body["summary"]["total"] == len(body["results"])


async def test_network_status_success(client: httpx.AsyncClient) -> None:
    response = await client.get("/network/status")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "network"
    assert "openwrt-01" in {item["host"]["name"] for item in body["results"]}


async def test_empty_kind_is_healthy_boundary(
    app: FastAPI,
    client_factory: Any,
) -> None:
    """边界：没有任何 docker 主机时，返回空列表而不是错误，且 healthy=true。"""
    app.dependency_overrides[get_inventory] = lambda: Inventory(hosts=[])
    async with client_factory(app) as client:
        response = await client.get("/docker/status")
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["summary"]["total"] == 0
    assert body["summary"]["healthy"] is True


async def test_probe_failure_is_503(
    app: FastAPI,
    client_factory: Any,
) -> None:
    """错误路径：探针抛异常 → CheckFailedError → 503 + 结构化错误。"""

    async def boom(_host: Host) -> int:
        raise TimeoutError("probe timed out")

    app.dependency_overrides[get_probe] = lambda: boom
    app.dependency_overrides[get_inventory] = lambda: Inventory(
        hosts=[Host(name="docker-01", kind="docker", address="192.168.1.20")]
    )
    async with client_factory(app) as client:
        response = await client.get("/docker/status")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "check_failed"
    assert body["error"]["hostname"] == "docker-01"
