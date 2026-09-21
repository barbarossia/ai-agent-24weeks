"""Automated tests validating MockAdapter, RealAdapter safety, and MCP Server integration."""

import json
import httpx
import pytest
from pathlib import Path
from pydantic import ValidationError
from homelab_mcp_server.models import RealAdapterConfig
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


def test_mock_adapter_ping():
    adapter = MockAdapter()
    result = adapter.ping()
    assert result["reachable"] is True
    assert result["mode"] == "mock"


def test_real_adapter_config_bare_ip_normalization():
    # A bare IP/host (no scheme) must be auto-normalized to http:// so httpx
    # does not raise UnsupportedProtocol.
    cfg = RealAdapterConfig(base_url="192.168.1.1")
    assert cfg.base_url == "http://192.168.1.1"

    cfg_with_port = RealAdapterConfig(base_url="192.168.1.1:8080")
    assert cfg_with_port.base_url == "http://192.168.1.1:8080"

    cfg_with_scheme = RealAdapterConfig(base_url="https://192.168.1.1:8443")
    assert cfg_with_scheme.base_url == "https://192.168.1.1:8443"


def test_real_adapter_ping_unreachable():
    # Non-routable/unresolvable host: ping() must not raise, and reports unreachable.
    cfg = RealAdapterConfig(base_url="http://homelab-api.example.invalid:8080", timeout_seconds=0.5)
    adapter = RealAdapter(config=cfg)
    result = adapter.ping()
    assert result["reachable"] is False
    assert result["mode"] == "real"
    assert "error" in result
    adapter.close()


def test_real_adapter_default_path_templates():
    cfg = RealAdapterConfig(base_url="http://homelab.local:8080")
    assert cfg.inventory_path == "/api/v1/inventory"
    assert cfg.health_list_path == "/api/v1/health"
    assert cfg.health_path_template == "/api/v1/health/{target_id}"
    assert cfg.metrics_path_template == "/api/v1/metrics/{target_id}"


def test_real_adapter_path_template_requires_placeholder():
    with pytest.raises(ValidationError):
        RealAdapterConfig(base_url="http://homelab.local:8080", health_path_template="/api/v1/health/fixed")
    with pytest.raises(ValidationError):
        RealAdapterConfig(base_url="http://homelab.local:8080", metrics_path_template="/api/v1/metrics/fixed")


def test_real_adapter_uses_configurable_paths():
    # Real devices (e.g. OpenWrt) rarely expose the default /api/v1/... REST
    # shape. Point path templates at whatever real read-only GET endpoint
    # actually exists (e.g. a small exporter/gateway) and verify the adapter
    # requests exactly that path -- without any real network I/O, using
    # httpx.MockTransport to record requested paths.
    requested_paths = []

    def handler(request):
        requested_paths.append(request.url.path)
        if "health" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "router-openwrt",
                    "name": "Main Gateway Router",
                    "status": "healthy",
                    "last_check_timestamp": "2026-09-21T16:00:00Z",
                    "details": "mock exporter response",
                },
            )
        return httpx.Response(200, json={"id": "router-openwrt", "name": "Main Gateway Router", "cpu_percent": 1.0})

    cfg = RealAdapterConfig(
        base_url="http://openwrt.lan",
        inventory_path="/cgi-bin/exporter/inventory",
        health_list_path="/cgi-bin/exporter/health",
        health_path_template="/cgi-bin/exporter/health/{target_id}",
        metrics_path_template="/cgi-bin/exporter/metrics/{target_id}",
    )
    adapter = RealAdapter(config=cfg)
    adapter._client = httpx.Client(
        base_url=adapter.base_url,
        transport=httpx.MockTransport(handler),
    )

    adapter.get_health(target_id="router-openwrt")
    adapter.get_metrics("router-openwrt")
    adapter.get_health()
    adapter.close()

    assert "/cgi-bin/exporter/health/router-openwrt" in requested_paths
    assert "/cgi-bin/exporter/metrics/router-openwrt" in requested_paths
    assert "/cgi-bin/exporter/health" in requested_paths


def test_example_config_files_are_valid():
    # examples/*.json must always parse into their respective config models,
    # so the documented sample files never silently rot out of sync.
    repo_root = Path(__file__).resolve().parent.parent
    examples_dir = repo_root / "examples"

    generic_cfg = RealAdapterConfig.model_validate_json(
        (examples_dir / "real_adapter_config.example.json").read_text(encoding="utf-8")
    )
    assert generic_cfg.base_url.startswith("http://")
    assert generic_cfg.inventory_path == "/api/v1/inventory"

    from homelab_mcp_server.models import OpenWrtAdapterConfig

    openwrt_cfg = OpenWrtAdapterConfig.model_validate_json(
        (examples_dir / "openwrt_config.example.json").read_text(encoding="utf-8")
    )
    assert openwrt_cfg.base_url == "http://192.168.1.1"
    assert openwrt_cfg.username == "root"


def test_real_adapter_config_validation():
    # Valid config
    cfg = RealAdapterConfig(base_url="http://homelab.local:8080", timeout_seconds=10.0)
    assert cfg.base_url == "http://homelab.local:8080"
    assert cfg.timeout_seconds == 10.0

    # Missing base_url
    with pytest.raises(ValidationError):
        RealAdapterConfig.model_validate_json('{"timeout_seconds": 5}')


def test_real_adapter_json_configuration(monkeypatch, tmp_path):
    # 1. Config via config_json
    json_str = json.dumps({"base_url": "http://homelab.local:8080", "auth_token": "token123", "timeout_seconds": 3.0})
    adapter1 = RealAdapter(config_json=json_str)
    assert adapter1.base_url == "http://homelab.local:8080"
    assert adapter1.config.timeout_seconds == 3.0
    adapter1.close()

    # 2. Config via config_file
    cfg_file = tmp_path / "homelab_config.json"
    cfg_file.write_text(json_str, encoding="utf-8")
    adapter2 = RealAdapter(config_file=str(cfg_file))
    assert adapter2.base_url == "http://homelab.local:8080"
    adapter2.close()

    # 3. Config via env HOMELAB_CONFIG_JSON
    monkeypatch.setenv("HOMELAB_CONFIG_JSON", json_str)
    adapter3 = RealAdapter()
    assert adapter3.base_url == "http://homelab.local:8080"
    adapter3.close()

    # 4. Error when unconfigured
    monkeypatch.delenv("HOMELAB_CONFIG_JSON", raising=False)
    with pytest.raises(ValueError, match="RealAdapter requires JSON-backed configuration"):
        RealAdapter()


def test_real_adapter_read_only_safety():
    cfg = RealAdapterConfig(base_url="http://mock-homelab.internal:8080", auth_token="dummy")
    adapter = RealAdapter(config=cfg)
    # Verify no mutating methods exist on adapter
    assert not hasattr(adapter, "post")
    assert not hasattr(adapter, "delete")
    assert not hasattr(adapter, "reboot")
    assert not hasattr(adapter, "shutdown")
    assert not hasattr(adapter, "update")
    adapter.close()
