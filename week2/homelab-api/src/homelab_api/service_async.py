"""异步业务层：把 Week 1 的同步 service 改造成 async，并演示并发控制。

**为什么 async 适合 Agent Tool？**
Agent 的工作负载几乎全是 I/O 等待：调用 LLM API、查向量库、访问 MCP Server、
探测主机……同步模型下，一个线程在等待 I/O 时只能阻塞；
asyncio 在**单线程事件循环**内用协程切换，等待期间去推进别的任务。
于是一个进程能用很小的内存同时推进成百上千个工具调用。

关键心智模型（与 C# / .NET 一致）：
- ``async def``    定义协程函数（≈ C# 的 ``async Task<T>``）；
- ``await``        挂起当前协程、把控制权还给事件循环（≈ ``await``）；
- ``asyncio.gather`` 并发等待多个协程（≈ ``Task.WhenAll``）；
- ``Semaphore``    限制同时在飞的协程数（≈ ``SemaphoreSlim``）。

**不要在 async 函数里写阻塞调用**（``time.sleep`` / ``requests`` / 同步文件 IO），
否则会卡住整个事件循环 —— 这正是本周要建立的直觉。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from ai_agent_lab.errors import CheckFailedError
from ai_agent_lab.models import CheckResult, HealthStatus, Host
from ai_agent_lab.service import classify, default_probe

__all__ = [
    "AsyncProbe",
    "ConcurrencyMeter",
    "make_async_probe",
    "async_probe",
    "check_host_async",
    "check_all_async",
]

# 探针协议（异步版）：输入 Host，返回可等待的延迟毫秒数。
# 对照 Week 1 的 ``Probe = Callable[[Host], int]``，这里只是把返回值包进了 Awaitable。
AsyncProbe = Callable[[Host], Awaitable[int]]

# 时间缩放：把"毫秒"映射为真实等待的秒数。
# 学习项目不真的去 ping 主机，用 asyncio.sleep 模拟 I/O 等待。
# 0.02 意味着 100ms 的延迟只等 2ms，测试快且仍足以观察并发。
DEFAULT_TIME_SCALE = 0.02


class ConcurrencyMeter:
    """记录"同时在飞的协程数"，用于**确定性地**验证并发行为。

    为什么不用墙钟时间断言并发？时间断言在 CI 上很脆弱（机器负载、调度抖动）。
    统计最大并发数则是确定性的：只要信号量生效，上限必然可预测。
    """

    __slots__ = ("current", "max_seen")

    def __init__(self) -> None:
        self.current = 0
        self.max_seen = 0

    def enter(self) -> None:
        self.current += 1
        if self.current > self.max_seen:
            self.max_seen = self.current

    def exit(self) -> None:
        self.current -= 1


def make_async_probe(
    *,
    time_scale: float = DEFAULT_TIME_SCALE,
    latency_fn: Callable[[Host], int] = default_probe,
) -> AsyncProbe:
    """构造一个异步探针。

    - ``latency_fn`` 沿用 Week 1 的 ``default_probe``：由主机名哈希派生，
      **确定性**，同一个 host 每次结果一致 → 测试不会 flaky。
    - ``asyncio.sleep`` 模拟真实 I/O 的等待；``time_scale=0`` 时几乎不等待，
      便于纯逻辑测试。
    """
    if time_scale < 0:
        raise ValueError("time_scale must be >= 0")

    async def probe(host: Host) -> int:
        latency_ms = latency_fn(host)
        if time_scale > 0:
            # 注意：这里是 await asyncio.sleep，而不是 time.sleep；
            # 前者让出事件循环，后者会阻塞整个进程。
            await asyncio.sleep((latency_ms / 1000.0) * time_scale)
        return latency_ms

    return probe


# 默认探针实例：供应用装配与文档示例使用。
async_probe: AsyncProbe = make_async_probe()


async def check_host_async(
    host: Host,
    probe: AsyncProbe = async_probe,
) -> CheckResult:
    """异步检查单台主机。

    与 Week 1 的 ``check_host`` 语义完全一致：探针异常统一包装为
    ``CheckFailedError``（领域异常），调用方不必认识底层异常类型。
    """
    try:
        latency_ms = await probe(host)
    except Exception as exc:  # noqa: BLE001 - 故意捕获所有探针异常并包装（同 Week 1 策略）
        raise CheckFailedError(host.name, str(exc)) from exc

    status = classify(host, latency_ms)
    message = {
        HealthStatus.UP: "ok",
        HealthStatus.DEGRADED: "high latency",
        HealthStatus.DOWN: "unreachable",
        HealthStatus.UNKNOWN: "unknown",
    }[status]
    return CheckResult(host=host, status=status, latency_ms=latency_ms, message=message)


async def check_all_async(
    hosts: Sequence[Host],
    probe: AsyncProbe = async_probe,
    concurrency: int = 4,
    meter: ConcurrencyMeter | None = None,
) -> list[CheckResult]:
    """并发检查多台主机，用信号量限制同时执行数。

    要点：
    - ``asyncio.gather`` 会保持**输入顺序**返回结果，无需手动排序。
    - ``Semaphore(concurrency)`` 保证同时在飞的探针不超过 ``concurrency`` 个，
      避免一次性打开过多连接把下游打垮（≈ C# 的 ``SemaphoreSlim``）。
    - 空列表也能正确返回 ``[]``。
    """
    if concurrency < 1:
        # 显式拒绝非法值；否则 Semaphore(0) 会让 gather 永久挂起（死锁）。
        raise ValueError("concurrency must be >= 1")

    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(host: Host) -> CheckResult:
        async with semaphore:
            if meter is not None:
                meter.enter()
            try:
                return await check_host_async(host, probe=probe)
            finally:
                if meter is not None:
                    meter.exit()

    return list(await asyncio.gather(*(run_one(host) for host in hosts)))
