"""Automated tests validating MockAdapter, RealAdapter safety, and MCP Server integration."""

import pytest
from homelab_mcp_server.mock_adapter import MockAdapter
from homelab_mcp_server.real_adapter import RealAdapter


def test_mock_adapter_inventory():
    adapter = MockAdapter()
    all_items = adapter.list_inventory()
    assert len(all_items) >= 4
    categories = {i.category for i in all_items}
    assert "hypervisor" in categories
    assert "database" in categories

    filtered = adapter.list_inventory(category_filter="database")
    assert len(filtered) == 1
    assert filtered[0].id == "db-postgres"


def test_mock_adapter_health():
    adapter = MockAdapter()
    all_health = adapter.get_health()
    assert len(all_health) >= 4

    esxi_health = adapter.get_health(target_id="hypervisor-esxi")
    assert len(esxi_health) == 1
    assert esxi_health[0].status == "degraded"
    assert "Datastore" in esxi_health[0].details


def test_mock_adapter_metrics():
    adapter = MockAdapter()
    metrics = adapter.get_metrics("hypervisor-esxi")
    assert metrics.cpu_percent == 68.2
    assert metrics.disk_percent == 92.4
    assert metrics.extra_stats.get("running_vms") == 6


def test_real_adapter_requires_base_url():
    with pytest.raises(ValueError, match="HOMELAB_BASE_URL must be configured"):
        RealAdapter(base_url="")


def test_real_adapter_read_only_safety():
    adapter = RealAdapter(base_url="http://mock-homelab.internal:8080", auth_token="dummy")
    # Verify no mutating methods exist on adapter
    assert not hasattr(adapter, "post")
    assert not hasattr(adapter, "delete")
    assert not hasattr(adapter, "reboot")
    assert not hasattr(adapter, "shutdown")
    assert not hasattr(adapter, "update")
    adapter.close()
