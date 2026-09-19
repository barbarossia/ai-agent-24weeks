"""共享测试夹具（fixtures）。"""

from __future__ import annotations

import pytest

from ai_agent_lab.models import Host, Inventory


@pytest.fixture
def esxi_host() -> Host:
    return Host(
        name="esxi-01",
        kind="esxi",  # StrEnum 接受字符串字面量
        address="192.168.1.10",
        tags=["Virtualization", "critical"],
        expected_latency_ms=120,
    )


@pytest.fixture
def inventory() -> Inventory:
    return Inventory.model_validate(
        {
            "hosts": [
                {"name": "esxi-01", "kind": "esxi", "address": "192.168.1.10",
                 "expected_latency_ms": 120},
                {"name": "docker-01", "kind": "docker", "address": "192.168.1.20",
                 "expected_latency_ms": 80},
            ]
        }
    )
