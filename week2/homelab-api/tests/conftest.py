"""共享测试夹具。

关键思路：每个测试拿到**全新的 app 实例**，并把探针覆盖成零等待版本，
使端点测试既快又确定。测试并发行为时则直接调用 service 层。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from homelab_api.deps import get_probe
from homelab_api.main import create_app
from homelab_api.service_async import make_async_probe

# 零等待探针：延迟数值仍是确定性的（由 Week 1 的哈希探针给出），只是不等真实时间。
FAST_PROBE = make_async_probe(time_scale=0.0)

ClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def app() -> FastAPI:
    """全新应用实例 + 默认覆盖为快速探针（测试可用 dependency_overrides 再改）。"""
    application = create_app()
    application.dependency_overrides[get_probe] = lambda: FAST_PROBE
    return application


@pytest.fixture
def client_factory():
    """按需为任意 app 构造 AsyncClient（用于测试中途改覆盖的场景）。"""

    @asynccontextmanager
    async def factory(application: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client

    return factory


@pytest.fixture
async def client(
    app: FastAPI,
    client_factory: ClientFactory,
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(app) as async_client:
        yield async_client
