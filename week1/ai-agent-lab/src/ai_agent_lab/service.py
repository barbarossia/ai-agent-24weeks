"""核心业务逻辑：加载清单、执行（模拟）检查、汇总结果。

分层意图（对应 C# 的分层思路）：
- ``models``   只管数据形状与校验；
- ``service``  只管业务规则，不认识命令行；
- ``cli``      只管解析参数与渲染输出。

这样 service 可以被 CLI、测试、以及未来的 FastAPI / MCP Server 复用。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import ValidationError

from .errors import CheckFailedError, InventoryError
from .models import (
    CheckResult,
    CheckSummary,
    HealthStatus,
    Host,
    Inventory,
)

__all__ = [
    "Probe",
    "DEFAULT_INVENTORY_DATA",
    "default_inventory",
    "load_inventory",
    "classify",
    "default_probe",
    "check_host",
    "check_all",
    "summarize",
]

# 探针协议：输入 Host，返回延迟毫秒数。可替换，便于测试注入。
# 类比 C# 的委托 / 接口（Func<Host, int>）。
Probe = Callable[[Host], int]

# 内置示例清单：保证 CLI 开箱即用，无需任何外部文件。
DEFAULT_INVENTORY_DATA: list[dict[str, object]] = [
    {
        "name": "esxi-01",
        "kind": "esxi",
        "address": "192.168.1.10",
        "tags": ["Virtualization", "critical"],
        "expected_latency_ms": 120,
    },
    {
        "name": "docker-01",
        "kind": "docker",
        "address": "192.168.1.20",
        "tags": ["containers", "critical"],
        "expected_latency_ms": 80,
    },
    {
        "name": "openwrt-01",
        "kind": "openwrt",
        "address": "192.168.1.1",
        "tags": ["network", "gateway"],
        "expected_latency_ms": 30,
    },
    {
        "name": "nas-01",
        "kind": "host",
        "address": "192.168.1.30",
        "tags": ["storage"],
        "expected_latency_ms": 60,
    },
]


def default_inventory() -> Inventory:
    """返回内置示例清单。"""
    return Inventory.model_validate({"hosts": DEFAULT_INVENTORY_DATA})


def load_inventory(path: Path) -> Inventory:
    """从 JSON 文件加载并校验清单。

    错误处理策略：把底层异常（文件 / JSON / Pydantic）统一包装为 ``InventoryError``，
    让调用方只需处理一种领域异常，同时用 ``raise ... from`` 保留根因。
    """
    if not path.is_file():
        raise InventoryError(f"inventory file not found: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:  # 权限 / IO 错误
        raise InventoryError(f"cannot read inventory file: {path}") from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise InventoryError(
            f"inventory is not valid JSON: {path} (line {exc.lineno}, column {exc.colno})"
        ) from exc

    try:
        return Inventory.model_validate(raw_data)
    except ValidationError as exc:
        raise InventoryError(
            f"inventory schema validation failed ({exc.error_count()} error(s)): {path}"
        ) from exc


def classify(host: Host, latency_ms: int) -> HealthStatus:
    """把延迟映射为健康状态。

    规则（故意简单，便于测试边界）：
    - ``latency <= expected``            → UP
    - ``expected < latency <= 2*expected`` → DEGRADED
    - 否则                                → DOWN
    """
    if latency_ms <= host.expected_latency_ms:
        return HealthStatus.UP
    if latency_ms <= host.expected_latency_ms * 2:
        return HealthStatus.DEGRADED
    return HealthStatus.DOWN


def default_probe(host: Host) -> int:
    """确定性的“模拟探针”。

    真实项目里这里会去 ping / 调 HTTP。学习项目不访问网络，用主机名派生一个**稳定**
    的延迟：同一个 host 每次运行结果一致，测试才不会 flaky。
    """
    digest = hashlib.sha256(host.name.encode("utf-8")).digest()
    jitter = digest[0] % 40  # 0..39
    return max(0, host.expected_latency_ms + jitter - 20)


def check_host(host: Host, probe: Probe = default_probe) -> CheckResult:
    """检查单台主机。

    探针本身可能抛异常；这里统一转换为 ``CheckFailedError``，保证调用方拿到的是
    领域异常，而不是随机的底层异常（类似 C# 里 catch 后 wrap 再 throw）。
    """
    try:
        latency_ms = probe(host)
    except Exception as exc:  # noqa: BLE001 - 故意捕获所有探针异常并包装
        raise CheckFailedError(host.name, str(exc)) from exc

    status = classify(host, latency_ms)
    message = {
        HealthStatus.UP: "ok",
        HealthStatus.DEGRADED: "high latency",
        HealthStatus.DOWN: "unreachable",
        HealthStatus.UNKNOWN: "unknown",
    }[status]
    return CheckResult(host=host, status=status, latency_ms=latency_ms, message=message)


def check_all(
    inventory: Inventory, probe: Probe = default_probe
) -> list[CheckResult]:
    """检查清单中的所有主机（保持清单顺序）。"""
    return [check_host(host, probe=probe) for host in inventory.hosts]


def summarize(results: Sequence[CheckResult]) -> CheckSummary:
    """汇总检查结果。"""
    counts = {status: 0 for status in HealthStatus}
    for result in results:
        counts[result.status] += 1
    return CheckSummary(
        total=len(results),
        up=counts[HealthStatus.UP],
        degraded=counts[HealthStatus.DEGRADED],
        down=counts[HealthStatus.DOWN],
        unknown=counts[HealthStatus.UNKNOWN],
    )
