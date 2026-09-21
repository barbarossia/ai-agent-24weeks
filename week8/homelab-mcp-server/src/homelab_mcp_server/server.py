"""HomeLab MCP Server exposing read-only inventory, health, and metrics tools."""

from __future__ import annotations

import json
import os
from typing import Optional
from mcp.server.fastmcp import FastMCP

from .models import BaseHomeLabAdapter
from .mock_adapter import MockAdapter
from .real_adapter import RealAdapter

# Factory function to instantiate adapter based on environment variable
def get_adapter() -> BaseHomeLabAdapter:
    mode = os.getenv("HOMELAB_MODE", "mock").lower()
    if mode == "real":
        return RealAdapter()
    return MockAdapter()


# Initialize MCP Server
mcp = FastMCP("homelab-service-mcp-server")
adapter: BaseHomeLabAdapter = get_adapter()


# ============================================================================
# READ-ONLY MCP TOOLS
# ============================================================================

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
