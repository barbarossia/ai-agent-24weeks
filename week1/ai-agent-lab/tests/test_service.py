"""业务逻辑测试：分类边界、探针注入、错误包装、清单加载。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_agent_lab.errors import CheckFailedError, InventoryError
from ai_agent_lab.models import HealthStatus, Host, Inventory
from ai_agent_lab.service import (
    check_all,
    check_host,
    classify,
    default_probe,
    default_inventory,
    load_inventory,
    summarize,
)

HOST = Host(name="esxi-01", kind="esxi", address="192.168.1.10", expected_latency_ms=100)


@pytest.mark.parametrize(
    ("latency", "expected"),
    [
        (0, HealthStatus.UP),
        (100, HealthStatus.UP),        # 边界：等于 expected → UP
        (101, HealthStatus.DEGRADED),  # 边界：刚超过 → DEGRADED
        (200, HealthStatus.DEGRADED),  # 边界：2x expected → DEGRADED
        (201, HealthStatus.DOWN),      # 边界：超过 2x → DOWN
    ],
)
def test_classify_boundaries(latency: int, expected: HealthStatus) -> None:
    assert classify(HOST, latency) is expected


def test_default_probe_is_deterministic() -> None:
    assert default_probe(HOST) == default_probe(HOST)
    assert default_probe(HOST) >= 0


def test_check_host_uses_injected_probe() -> None:
    """依赖注入：传入固定探针即可完全掌控结果，无需网络。"""
    result = check_host(HOST, probe=lambda host: 250)
    assert result.status is HealthStatus.DOWN
    assert result.latency_ms == 250
    assert result.host.name == "esxi-01"


def test_check_host_wraps_probe_exception() -> None:
    def boom(_host: Host) -> int:
        raise TimeoutError("probe timed out")

    with pytest.raises(CheckFailedError) as excinfo:
        check_host(HOST, probe=boom)

    assert excinfo.value.hostname == "esxi-01"
    assert "timed out" in excinfo.value.reason
    # 根因被保留在异常链里
    assert isinstance(excinfo.value.__cause__, TimeoutError)


def test_check_all_preserves_order_and_summary(inventory: Inventory) -> None:
    results = check_all(inventory, probe=lambda host: 10)
    assert [r.host.name for r in results] == ["esxi-01", "docker-01"]

    summary = summarize(results)
    assert summary.total == 2
    assert summary.up == 2
    assert summary.healthy is True


def test_summarize_empty_is_healthy() -> None:
    summary = summarize([])
    assert summary.total == 0
    assert summary.healthy is True


# --- load_inventory：文件 / JSON / schema 三层错误处理 ---


def test_load_inventory_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InventoryError, match="not found"):
        load_inventory(tmp_path / "nope.json")


def test_load_inventory_invalid_json(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(InventoryError, match="not valid JSON"):
        load_inventory(broken)


def test_load_inventory_schema_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"hosts": [{"name": ""}]}), encoding="utf-8")
    with pytest.raises(InventoryError, match="schema validation failed"):
        load_inventory(bad)


def test_load_inventory_success(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"hosts": [{"name": "a-01", "kind": "host", "address": "10.0.0.1"}]}),
        encoding="utf-8",
    )
    inv = load_inventory(good)
    assert [h.name for h in inv.hosts] == ["a-01"]


def test_default_inventory_is_valid() -> None:
    inv = default_inventory()
    assert len(inv.hosts) == 4
    assert {h.kind.value for h in inv.hosts} == {"esxi", "docker", "openwrt", "host"}
