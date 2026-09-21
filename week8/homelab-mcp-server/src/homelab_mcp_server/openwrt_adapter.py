"""OpenWrtUbusAdapter: a genuine, working integration with real OpenWrt routers
via their native management interface, ubus-over-HTTP (the same '/ubus'
JSON-RPC 2.0 endpoint that LuCI itself uses).

This is intentionally NOT a fictional REST API. OpenWrt does not expose a
'/api/v1/...' style GET-only REST interface; its real interface requires a
session-authenticated JSON-RPC call over HTTP POST:

    POST /ubus
    {"jsonrpc": "2.0", "id": 1, "method": "call",
     "params": [<session_id>, <object>, <method>, {<args>}]}

Safety Constraints (read-only, despite using HTTP POST at the transport level):
- Only a fixed, hardcoded allowlist of known read-only ubus (object, method)
  pairs may ever be called: `system.board`, `system.info`,
  `network.interface.dump`, `network.device.status`.
- There is no pass-through/arbitrary ubus 'call' capability exposed to callers;
  no user input can select an arbitrary ubus object/method.
- No mutating ubus calls (e.g. 'system.reboot', 'network.interface.up/down',
  'file.*') are implemented or reachable through this adapter.
- Credentials (username/password) are never logged or persisted; the ubus
  session id is kept only in memory for the lifetime of the adapter instance.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import httpx
from .models import BaseHomeLabAdapter, BasicMetrics, DeviceOrService, HealthStatus, OpenWrtAdapterConfig

# Fixed allowlist of read-only ubus (object, method) pairs this adapter may call.
# This is defense-in-depth: no code path in this file passes user-controlled
# object/method values into _ubus_call; the allowlist exists so any future
# modification cannot accidentally introduce a mutating call without also
# updating (and re-reviewing) this explicit list.
_ALLOWED_UBUS_CALLS = {
    ("session", "login"),
    ("system", "board"),
    ("system", "info"),
    ("network.interface", "dump"),
    ("network.device", "status"),
}

_ANONYMOUS_SESSION_ID = "00000000000000000000000000000000"


class OpenWrtAdapter(BaseHomeLabAdapter):
    """Read-only adapter for a real OpenWrt router via ubus-over-HTTP."""

    def __init__(self, config: OpenWrtAdapterConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )
        self._session_id: Optional[str] = None

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # ubus JSON-RPC transport
    # ------------------------------------------------------------------

    def _ubus_call(self, session_id: str, obj: str, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a single allowlisted, read-only ubus call. Raises RuntimeError
        on ubus-level errors; raises httpx.HTTPError on transport failures."""
        if (obj, method) not in _ALLOWED_UBUS_CALLS:
            # Defense-in-depth: should be unreachable given this file's own call sites.
            raise ValueError(f"ubus call '{obj}.{method}' is not in the read-only allowlist")

        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1_000_000,
            "method": "call",
            "params": [session_id, obj, method, params or {}],
        }
        resp = self._client.post("/ubus", json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"ubus JSON-RPC error calling {obj}.{method}: {data['error']}")

        result = data.get("result")
        if not result or not isinstance(result, list):
            raise RuntimeError(f"ubus call {obj}.{method} returned an unexpected response: {data}")

        status_code = result[0]
        if status_code != 0:
            raise RuntimeError(f"ubus call {obj}.{method} failed with ubus status {status_code}")

        return result[1] if len(result) > 1 else {}

    def _ensure_session(self) -> str:
        """Log in (once) via the real ubus 'session'/'login' call and cache the session id."""
        if self._session_id:
            return self._session_id
        result = self._ubus_call(
            _ANONYMOUS_SESSION_ID,
            "session",
            "login",
            {"username": self.config.username, "password": self.config.password},
        )
        session_id = result.get("ubus_rpc_session")
        if not session_id:
            raise RuntimeError("ubus session login did not return 'ubus_rpc_session'")
        self._session_id = session_id
        return session_id

    def _authed_call(self, obj: str, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Call an allowlisted ubus method using the cached session, re-logging in
        once if the session was rejected (ubus status 6 == UBUS_STATUS_PERMISSION_DENIED)."""
        session_id = self._ensure_session()
        try:
            return self._ubus_call(session_id, obj, method, params)
        except RuntimeError as exc:
            if "ubus status 6" in str(exc):
                self._session_id = None
                session_id = self._ensure_session()
                return self._ubus_call(session_id, obj, method, params)
            raise

    # ------------------------------------------------------------------
    # BaseHomeLabAdapter contract
    # ------------------------------------------------------------------

    def ping(self) -> Dict[str, Any]:
        """Read-only connectivity check: performs a real ubus session login only.
        Never raises; reports reachability instead."""
        try:
            self._ensure_session()
            return {"reachable": True, "mode": "openwrt", "base_url": self.base_url}
        except (httpx.HTTPError, RuntimeError) as exc:
            return {
                "reachable": False,
                "mode": "openwrt",
                "base_url": self.base_url,
                "error": f"{exc.__class__.__name__}: {str(exc)}",
            }

    def list_inventory(self, category_filter: Optional[str] = None) -> List[DeviceOrService]:
        items: List[DeviceOrService] = []
        try:
            board = self._authed_call("system", "board")
            items.append(
                DeviceOrService(
                    id="router-openwrt",
                    name=board.get("hostname", "OpenWrt Router"),
                    category="router",
                    host=self.base_url,
                    ip=self.base_url.split("://")[-1].split(":")[0],
                )
            )
        except (httpx.HTTPError, RuntimeError):
            pass

        try:
            dump = self._authed_call("network.interface", "dump")
            for iface in dump.get("interface", []):
                items.append(
                    DeviceOrService(
                        id=f"iface-{iface.get('interface', 'unknown')}",
                        name=f"Interface: {iface.get('interface', 'unknown')}",
                        category="network-interface",
                        host=iface.get("l3_device") or iface.get("device") or "n/a",
                    )
                )
        except (httpx.HTTPError, RuntimeError):
            pass

        if category_filter:
            items = [i for i in items if i.category.lower() == category_filter.lower()]
        return items

    def get_health(self, target_id: Optional[str] = None) -> List[HealthStatus]:
        results: List[HealthStatus] = []

        want_router = target_id is None or target_id == "router-openwrt"
        want_iface = target_id is None or target_id.startswith("iface-")

        if want_router:
            try:
                info = self._authed_call("system", "info")
                results.append(
                    HealthStatus(
                        id="router-openwrt",
                        name="OpenWrt Router",
                        status="healthy",
                        last_check_timestamp=str(int(time.time())),
                        details=f"uptime={info.get('uptime')}s, ubus reachable",
                    )
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                results.append(
                    HealthStatus(
                        id="router-openwrt",
                        name="OpenWrt Router",
                        status="down",
                        last_check_timestamp=str(int(time.time())),
                        details=f"ubus unreachable: {exc.__class__.__name__}: {exc}",
                    )
                )

        if want_iface:
            try:
                dump = self._authed_call("network.interface", "dump")
                for iface in dump.get("interface", []):
                    iface_id = f"iface-{iface.get('interface', 'unknown')}"
                    if target_id and target_id != iface_id:
                        continue
                    up = bool(iface.get("up"))
                    results.append(
                        HealthStatus(
                            id=iface_id,
                            name=f"Interface: {iface.get('interface', 'unknown')}",
                            status="healthy" if up else "down",
                            last_check_timestamp=str(int(time.time())),
                            details=f"proto={iface.get('proto')}, up={up}",
                        )
                    )
            except (httpx.HTTPError, RuntimeError):
                pass

        return results

    def get_metrics(self, target_id: str) -> BasicMetrics:
        if target_id == "router-openwrt":
            try:
                info = self._authed_call("system", "info")
                load = info.get("load", [0, 0, 0])
                memory = info.get("memory", {})
                mem_total = memory.get("total", 0)
                mem_free = memory.get("free", 0)
                memory_percent = ((mem_total - mem_free) / mem_total * 100.0) if mem_total else None
                return BasicMetrics(
                    id=target_id,
                    name="OpenWrt Router",
                    memory_percent=memory_percent,
                    extra_stats={
                        # ubus reports load averages pre-multiplied by 65536,
                        # matching Linux /proc/loadavg convention.
                        "load_1min": round(load[0] / 65536.0, 2) if len(load) > 0 else None,
                        "load_5min": round(load[1] / 65536.0, 2) if len(load) > 1 else None,
                        "load_15min": round(load[2] / 65536.0, 2) if len(load) > 2 else None,
                        "uptime_seconds": info.get("uptime"),
                        "note": "cpu_percent is not reported by ubus system.info; see load_*min instead",
                    },
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                return BasicMetrics(
                    id=target_id,
                    name="OpenWrt Router",
                    extra_stats={"error": f"ubus unreachable: {exc.__class__.__name__}: {exc}"},
                )

        # Per-interface metrics: resolve the interface's L3 device, then query
        # network.device status for raw (cumulative) traffic counters.
        try:
            dump = self._authed_call("network.interface", "dump")
            device_name = None
            for iface in dump.get("interface", []):
                if f"iface-{iface.get('interface')}" == target_id:
                    device_name = iface.get("l3_device") or iface.get("device")
                    break
            if not device_name:
                return BasicMetrics(id=target_id, name=target_id, extra_stats={"error": "unknown interface"})

            status = self._authed_call("network.device", "status", {"name": device_name})
            stats = status.get("statistics", {})
            return BasicMetrics(
                id=target_id,
                name=f"Interface: {device_name}",
                extra_stats={
                    "rx_bytes_total": stats.get("rx_bytes"),
                    "tx_bytes_total": stats.get("tx_bytes"),
                    "note": "cumulative byte counters from ubus network.device.status, not a rate",
                },
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            return BasicMetrics(
                id=target_id,
                name=target_id,
                extra_stats={"error": f"ubus unreachable: {exc.__class__.__name__}: {exc}"},
            )
