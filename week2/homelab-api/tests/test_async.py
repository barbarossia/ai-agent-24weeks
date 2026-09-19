"""异步执行模型 + 并发控制（service 层，不经过 HTTP）。"""

from __future__ import annotations

import pytest

from ai_agent_lab.errors import CheckFailedError
from ai_agent_lab.models import Host
from homelab_api.service_async import (
    ConcurrencyMeter,
    check_all_async,
    check_host_async,
    make_async_probe,
)

HOST = Host(name="esxi-01", kind="esxi", address="192.168.1.10")


def _hosts(count: int) -> list[Host]:
    return [
        Host(name=f"h-{index:02d}", kind="host", address="10.0.0.1")
        for index in range(count)
    ]


async def test_async_probe_is_deterministic() -> None:
    probe = make_async_probe(time_scale=0.0)
    assert await probe(HOST) == await probe(HOST)
    assert await probe(HOST) >= 0


async def test_make_async_probe_rejects_negative_scale() -> None:
    with pytest.raises(ValueError):
        make_async_probe(time_scale=-1)


async def test_check_host_async_uses_injected_probe() -> None:
    async def fixed(_host: Host) -> int:
        return 250

    result = await check_host_async(HOST, probe=fixed)
    assert result.latency_ms == 250
    assert result.status.value == "down"


async def test_check_host_async_wraps_probe_exception() -> None:
    async def boom(_host: Host) -> int:
        raise TimeoutError("probe timed out")

    with pytest.raises(CheckFailedError) as excinfo:
        await check_host_async(HOST, probe=boom)

    assert excinfo.value.hostname == "esxi-01"
    assert "timed out" in excinfo.value.reason
    # 根因保留在异常链里（与 Week 1 策略一致）
    assert isinstance(excinfo.value.__cause__, TimeoutError)


async def test_gather_is_concurrent_and_bounded() -> None:
    """并发确实发生（max_seen > 1），但不超过信号量容量（<= 4）。"""
    meter = ConcurrencyMeter()
    hosts = _hosts(8)
    results = await check_all_async(
        hosts,
        probe=make_async_probe(time_scale=0.05),
        concurrency=4,
        meter=meter,
    )
    # gather 保持输入顺序
    assert [result.host.name for result in results] == [host.name for host in hosts]
    assert meter.max_seen > 1
    assert meter.max_seen <= 4


async def test_semaphore_limit_of_two() -> None:
    meter = ConcurrencyMeter()
    await check_all_async(
        _hosts(10),
        probe=make_async_probe(time_scale=0.05),
        concurrency=2,
        meter=meter,
    )
    assert meter.max_seen > 1
    assert meter.max_seen <= 2


async def test_empty_hosts_returns_empty() -> None:
    assert await check_all_async([], concurrency=4) == []


async def test_invalid_concurrency_is_rejected() -> None:
    """边界：concurrency=0 若不拒绝，Semaphore(0) 会让 gather 永久挂起。"""
    with pytest.raises(ValueError, match="concurrency"):
        await check_all_async(_hosts(1), concurrency=0)
