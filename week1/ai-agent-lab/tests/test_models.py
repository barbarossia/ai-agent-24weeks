"""Pydantic 模型行为测试：校验、归一化、不可变性。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_agent_lab.models import CheckSummary, HealthStatus, Host, Inventory


def test_host_accepts_valid_payload(esxi_host: Host) -> None:
    assert esxi_host.name == "esxi-01"
    assert esxi_host.kind.value == "esxi"
    assert esxi_host.expected_latency_ms == 120


def test_tags_are_normalized_sorted_and_deduplicated() -> None:
    host = Host(
        name="nas-01",
        kind="host",
        address="192.168.1.30",
        tags=[" Storage ", "storage", "CRITICAL", ""],
    )
    assert host.tags == ["critical", "storage"]


@pytest.mark.parametrize("bad_name", ["", "-leading-dash", "has space", "a" * 64])
def test_invalid_hostname_is_rejected(bad_name: str) -> None:
    with pytest.raises(ValidationError):
        Host(name=bad_name, kind="host", address="10.0.0.1")


def test_unknown_field_is_forbidden() -> None:
    """extra='forbid'：拼错的字段应当直接报错，而不是被静默忽略。"""
    with pytest.raises(ValidationError):
        Host(name="x", kind="host", address="10.0.0.1", expexted_latency_ms=5)  # type: ignore[call-arg]


def test_host_is_immutable(esxi_host: Host) -> None:
    with pytest.raises(ValidationError):
        esxi_host.address = "10.9.9.9"  # type: ignore[misc]


def test_inventory_rejects_duplicate_names() -> None:
    with pytest.raises(ValidationError, match="duplicate host"):
        Inventory.model_validate(
            {
                "hosts": [
                    {"name": "dup", "kind": "host", "address": "10.0.0.1"},
                    {"name": "dup", "kind": "host", "address": "10.0.0.2"},
                ]
            }
        )


def test_inventory_find_returns_none_when_missing(inventory: Inventory) -> None:
    assert inventory.find("docker-01") is not None
    assert inventory.find("nope") is None


def test_check_summary_health_rule() -> None:
    healthy = CheckSummary(total=2, up=2, degraded=0, down=0, unknown=0)
    degraded = CheckSummary(total=2, up=1, degraded=1, down=0, unknown=0)
    broken = CheckSummary(total=2, up=1, degraded=1, down=1, unknown=0)

    assert healthy.healthy is True
    assert degraded.healthy is True  # DEGRADED 仍算健康，只是需要关注
    assert broken.healthy is False
    assert degraded.as_dict()["healthy"] is True


def test_health_status_is_string_enum() -> None:
    # StrEnum 成员可直接当字符串比较 / 序列化
    assert HealthStatus.UP == "up"
