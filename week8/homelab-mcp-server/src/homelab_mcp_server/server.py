"""HomeLab MCP Server exposing read-only inventory, health, and metrics tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP

from .models import BaseHomeLabAdapter, OpenWrtAdapterConfig
from .mock_adapter import MockAdapter
from .openwrt_adapter import OpenWrtAdapter

# Factory function to instantiate adapter based on environment variable
def get_adapter() -> BaseHomeLabAdapter:
    mode = os.getenv("HOMELAB_MODE", "mock").lower()
    if mode == "openwrt":
        if "OPENWRT_CONFIG_JSON" in os.environ:
            cfg = OpenWrtAdapterConfig.model_validate_json(os.environ["OPENWRT_CONFIG_JSON"])
        elif "OPENWRT_CONFIG_FILE" in os.environ:
            raw_text = Path(os.environ["OPENWRT_CONFIG_FILE"]).read_text(encoding="utf-8")
            cfg = OpenWrtAdapterConfig.model_validate_json(raw_text)
        else:
            raise ValueError(
                "HOMELAB_MODE=openwrt requires OPENWRT_CONFIG_JSON or OPENWRT_CONFIG_FILE "
                "to be set (JSON-backed OpenWrtAdapterConfig)."
            )
        return OpenWrtAdapter(cfg)
    return MockAdapter()


# Initialize MCP Server
mcp = FastMCP("homelab-service-mcp-server")
adapter: BaseHomeLabAdapter = get_adapter()


# ============================================================================
# READ-ONLY MCP TOOLS
# ============================================================================

@mcp.tool()
def ping() -> str:
    """Application-level status tool (NOT the MCP protocol connectivity check).

    For the actual MCP protocol-level connection/liveness check, clients should
    call `ClientSession.send_ping()`, which sends a `PingRequest` and expects
    an `EmptyResult` — this is handled automatically by the MCP SDK and does
    not require a custom tool. This `ping` tool additionally exercises the
    underlying adapter's read-only `ping()` connectivity check (a real ubus
    session login for `OpenWrtAdapter`, a no-op confirmation for
    `MockAdapter`).

    Returns:
        JSON string confirming server status, adapter mode, adapter reachability,
        and read-only guarantee.
    """
    if isinstance(adapter, OpenWrtAdapter):
        mode = "openwrt"
    else:
        mode = "mock"
    adapter_ping = adapter.ping()
    return json.dumps({
        "status": "pong",
        "server": "homelab-service-mcp-server",
        "adapter_mode": mode,
        "adapter_ping": adapter_ping,
        "read_only": True,
    })


@mcp.tool()
def list_devices_and_services(category: Optional[str] = None) -> str:
    """List homelab devices and services in inventory.

    Args:
        category: Optional filter by category (e.g., 'hypervisor', 'database', 'router', 'container', 'storage').
    """
    items = adapter.list_inventory(category_filter=category)
    return json.dumps([item.model_dump() for item in items], indent=2)


@mcp.tool()
def get_health_status(target_id: Optional[str] = None) -> str:
    """Retrieve health checks, availability status, and latency for homelab targets.

    Args:
        target_id: Optional specific target id (e.g., 'hypervisor-esxi', 'router-openwrt', 'db-postgres').
                   If omitted, returns health checks for all targets.
    """
    statuses = adapter.get_health(target_id=target_id)
    return json.dumps([s.model_dump() for s in statuses], indent=2)


@mcp.tool()
def get_basic_metrics(target_id: str) -> str:
    """Query current resource utilization metrics (CPU, RAM, Disk, Network I/O) for a target.

    Args:
        target_id: Target identifier (e.g., 'hypervisor-esxi', 'db-postgres', 'router-openwrt').
    """
    metrics = adapter.get_metrics(target_id=target_id)
    return json.dumps(metrics.model_dump(), indent=2)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
