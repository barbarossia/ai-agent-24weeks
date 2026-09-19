"""主机路由：成功路径 + 错误/边界路径（404、422）。"""

from __future__ import annotations

import httpx


async def test_list_hosts_success(client: httpx.AsyncClient) -> None:
    response = await client.get("/hosts")
    assert response.status_code == 200
    assert [host["name"] for host in response.json()] == [
        "esxi-01",
        "docker-01",
        "openwrt-01",
        "nas-01",
    ]


async def test_get_host_success(client: httpx.AsyncClient) -> None:
    response = await client.get("/hosts/esxi-01")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "esxi-01"
    assert body["kind"] == "esxi"


async def test_get_host_not_found_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/hosts/nope-99")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "host_not_found"
    assert body["error"]["hostname"] == "nope-99"


async def test_post_check_success(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/hosts/check",
        json={"names": ["esxi-01", "docker-01"], "concurrency": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["host"]["name"] for item in body["results"]] == [
        "esxi-01",
        "docker-01",
    ]
    assert body["summary"]["total"] == 2
    assert body["summary"]["up"] == 2
    assert body["summary"]["healthy"] is True


async def test_post_check_unknown_host_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/hosts/check", json={"names": ["ghost-01"]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "host_not_found"


async def test_post_check_empty_names_is_422(client: httpx.AsyncClient) -> None:
    """边界：names 为空列表 → Pydantic 请求校验失败 → 统一 422 外壳。"""
    response = await client.post("/hosts/check", json={"names": []})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_post_check_out_of_range_concurrency_is_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/hosts/check", json={"names": ["esxi-01"], "concurrency": 0}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_post_check_extra_field_is_422(client: httpx.AsyncClient) -> None:
    """extra="forbid"：客户端多传字段直接 422，而不是被静默忽略。"""
    response = await client.post(
        "/hosts/check", json={"names": ["esxi-01"], "bogus": 1}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
