"""Automated tests validating MockAdapter, MCP Server integration, and configuration examples."""

from pathlib import Path
from homelab_mcp_server.models import OpenWrtAdapterConfig
from homelab_mcp_server.mock_adapter import MockAdapter


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


def test_mock_adapter_ping():
    adapter = MockAdapter()
    result = adapter.ping()
    assert result["reachable"] is True
    assert result["mode"] == "mock"


def test_openwrt_adapter_config_bare_ip_normalization():
    # A bare IP/host (no scheme) must be auto-normalized to http:// so httpx
    # does not raise UnsupportedProtocol.
    cfg = OpenWrtAdapterConfig(base_url="192.168.1.1", password="dummy")
    assert cfg.base_url == "http://192.168.1.1"

    cfg_with_port = OpenWrtAdapterConfig(base_url="192.168.1.1:8080", password="dummy")
    assert cfg_with_port.base_url == "http://192.168.1.1:8080"

    cfg_with_scheme = OpenWrtAdapterConfig(base_url="https://192.168.1.1:8443", password="dummy")
    assert cfg_with_scheme.base_url == "https://192.168.1.1:8443"


def test_example_config_files_are_valid():
    # examples/*.json must always parse into their respective config models,
    # so the documented sample files never silently rot out of sync.
    repo_root = Path(__file__).resolve().parent.parent
    examples_dir = repo_root / "examples"

    openwrt_cfg = OpenWrtAdapterConfig.model_validate_json(
        (examples_dir / "openwrt_config.example.json").read_text(encoding="utf-8")
    )
    assert openwrt_cfg.base_url == "http://192.168.1.1"
    assert openwrt_cfg.username == "root"
