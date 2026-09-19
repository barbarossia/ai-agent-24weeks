"""可运行的异步 HTTP 客户端示例。

运行：``uv run python examples/async_http_client.py``

不访问外网：用 ``httpx.ASGITransport`` 把请求直接送进进程内的 ASGI app。
想连真实服务器时，把 ``transport=...`` 去掉、把 base_url 换成
``http://127.0.0.1:8000`` 即可（先另开终端 ``uv run homelab-api``）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from homelab_api.deps import get_probe
from homelab_api.main import create_app
from homelab_api.service_async import make_async_probe


async def main() -> int:
    app = create_app()
    # 演示用：把探针换成零等待，脚本秒出结果。
    app.dependency_overrides[get_probe] = lambda: make_async_probe(time_scale=0.0)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        # 1) 并发发三个 GET，等待时间取三者最大值而非相加。
        health, hosts, docker = await asyncio.gather(
            client.get("/health"),
            client.get("/hosts"),
            client.get("/docker/status"),
        )

        print("[health]", json.dumps(health.json(), ensure_ascii=False))
        print("[hosts] ", [h["name"] for h in hosts.json()])
        print("[docker]", json.dumps(docker.json()["summary"], ensure_ascii=False))

        # 2) 错误路径：未知主机 → 404 且带结构化 error.code。
        missing = await client.get("/hosts/ghost-01")
        print("[404]   ", missing.status_code, missing.json()["error"]["code"])

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
