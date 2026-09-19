"""异步 HTTP 客户端示例：httpx.AsyncClient + ASGITransport。

不需要启动服务器、不需要真实网络：ASGITransport 直接把请求送进 ASGI app。
这既是"能写 async HTTP client"的练习载体，也是测试 FastAPI 的现代方式。
"""

from __future__ import annotations

import asyncio

import httpx

from homelab_api.deps import get_probe
from homelab_api.main import create_app
from homelab_api.service_async import make_async_probe


async def test_async_client_parallel_requests() -> None:
    app = create_app()
    app.dependency_overrides[get_probe] = lambda: make_async_probe(time_scale=0.0)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        # 两个请求并发发出：asyncio.gather 等价于 C# 的 Task.WhenAll。
        health, hosts = await asyncio.gather(
            client.get("/health"),
            client.get("/hosts"),
        )

    assert health.status_code == 200
    assert hosts.status_code == 200
    assert len(hosts.json()) == 4
