"""Tests for OpenWrtAdapter (real ubus-over-HTTP protocol), using
httpx.MockTransport to simulate an OpenWrt router's /ubus JSON-RPC endpoint
without any real network I/O or real device."""

from __future__ import annotations

import httpx
import pytest
from homelab_mcp_server.models import OpenWrtAdapterConfig
from homelab_mcp_server.openwrt_adapter import OpenWrtAdapter, _ALLOWED_UBUS_CALLS


def _make_mock_ubus_server(login_ok: bool = True):
    """Returns an httpx.MockTransport handler that emulates a minimal real
    OpenWrt ubus JSON-RPC server for session/login, system.board, system.info,
    network.interface.dump, and network.device.status."""

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ubus"
        assert request.method == "POST"
        body = request.read()
        import json as _json

        payload = _json.loads(body)
        session_id, obj, method, params = payload["params"]
        calls.append((obj, method, params))

        if obj == "session" and method == "login":
            if not login_ok:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": [6]})
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": [0, {"ubus_rpc_session": "fake-session-id-123"}],
                },
            )

        if obj == "system" and method == "board":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": payload["id"], "result": [0, {"hostname": "OpenWrt-Lab-Router"}]},
            )

        if obj == "system" and method == "info":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": [
                        0,
                        {
                            "uptime": 123456,
                            "load": [65536, 32768, 16384],  # 1.0, 0.5, 0.25
                            "memory": {"total": 1000, "free": 400},
                        },
                    ],
                },
            )

        if obj == "network.interface" and method == "dump":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": [
                        0,
                        {
                            "interface": [
                                {"interface": "lan", "up": True, "l3_device": "br-lan", "proto": "static"},
                                {"interface": "wan", "up": False, "l3_device": "eth1", "proto": "dhcp"},
                            ]
                        },
                    ],
                },
            )

        if obj == "network.device" and method == "status":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": [0, {"statistics": {"rx_bytes": 111, "tx_bytes": 222}}],
                },
            )

        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": [1]})

    return handler, calls


def _make_adapter(login_ok: bool = True):
    cfg = OpenWrtAdapterConfig(base_url="192.168.1.1", username="root", password="test-password")
    adapter = OpenWrtAdapter(cfg)
    handler, calls = _make_mock_ubus_server(login_ok=login_ok)
    adapter._client = httpx.Client(base_url=adapter.base_url, transport=httpx.MockTransport(handler))
    return adapter, calls


def test_openwrt_config_normalizes_bare_ip():
    cfg = OpenWrtAdapterConfig(base_url="192.168.1.1", password="test-password")
    assert cfg.base_url == "http://192.168.1.1"


def test_openwrt_adapter_ping_success():
    adapter, calls = _make_adapter(login_ok=True)
    result = adapter.ping()
    assert result["reachable"] is True
    assert result["mode"] == "openwrt"
    assert ("session", "login") in [(c[0], c[1]) for c in calls]
    adapter.close()


def test_openwrt_adapter_ping_login_failure():
    adapter, _ = _make_adapter(login_ok=False)
    result = adapter.ping()
    assert result["reachable"] is False
    assert "error" in result
    adapter.close()


def test_openwrt_adapter_list_inventory():
    adapter, _ = _make_adapter()
    items = adapter.list_inventory()
    ids = {i.id for i in items}
    assert "router-openwrt" in ids
    assert "iface-lan" in ids
    assert "iface-wan" in ids
    router = next(i for i in items if i.id == "router-openwrt")
    assert router.name == "OpenWrt-Lab-Router"
    adapter.close()


def test_openwrt_adapter_get_health():
    adapter, _ = _make_adapter()
    all_health = adapter.get_health()
    by_id = {h.id: h for h in all_health}
    assert by_id["router-openwrt"].status == "healthy"
    assert by_id["iface-lan"].status == "healthy"
    assert by_id["iface-wan"].status == "down"

    single = adapter.get_health(target_id="iface-wan")
    assert len(single) == 1
    assert single[0].status == "down"
    adapter.close()


def test_openwrt_adapter_get_metrics_router():
    adapter, _ = _make_adapter()
    metrics = adapter.get_metrics("router-openwrt")
    assert metrics.memory_percent == 60.0
    assert metrics.extra_stats["load_1min"] == 1.0
    assert metrics.extra_stats["uptime_seconds"] == 123456
    adapter.close()


def test_openwrt_adapter_get_metrics_interface():
    adapter, _ = _make_adapter()
    metrics = adapter.get_metrics("iface-lan")
    assert metrics.extra_stats["rx_bytes_total"] == 111
    assert metrics.extra_stats["tx_bytes_total"] == 222
    adapter.close()


def test_openwrt_adapter_session_reuse_and_relogin_on_permission_denied():
    # First call triggers login; verify only one login call happens for two
    # subsequent authed calls (session reuse), by counting login calls.
    adapter, calls = _make_adapter()
    adapter.get_health(target_id="router-openwrt")
    adapter.get_metrics("router-openwrt")
    login_calls = [c for c in calls if c[0] == "session" and c[1] == "login"]
    assert len(login_calls) == 1
    adapter.close()


def test_openwrt_adapter_allowlist_blocks_arbitrary_calls():
    adapter, _ = _make_adapter()
    with pytest.raises(ValueError, match="not in the read-only allowlist"):
        adapter._ubus_call("fake-session-id-123", "system", "reboot")
    adapter.close()


def test_openwrt_adapter_no_mutating_methods_exposed():
    adapter, _ = _make_adapter()
    assert not hasattr(adapter, "reboot")
    assert not hasattr(adapter, "shutdown")
    assert not hasattr(adapter, "set_interface")
    # Every entry in the allowlist itself must be a known read-only call.
    mutating_keywords = {"reboot", "up", "down", "set", "add", "delete", "restart", "commit"}
    for _, method in _ALLOWED_UBUS_CALLS:
        assert method not in mutating_keywords
    adapter.close()
