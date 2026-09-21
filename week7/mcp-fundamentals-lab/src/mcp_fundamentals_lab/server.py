"""Minimal, official MCP Server implementation covering Tools, Resources, and Prompts.

Uses FastMCP from the official `mcp` Python SDK (v1.3.0).
Provides standard stdio transport for client connection.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("homelab-mcp-server")

# Mock dataset for HomeLab infrastructure
HOMELAB_STORE = {
    "hosts": {
        "web01": {"status": "up", "ip": "192.168.1.10", "role": "web-frontend"},
        "db01": {"status": "up", "ip": "192.168.1.20", "role": "database-cluster"},
        "esxi01": {"status": "down", "ip": "192.168.1.2", "role": "hypervisor"},
    },
    "logs": {
        "web01": "2026-09-21 15:00:01 INFO [nginx] 200 GET /index.html\n2026-09-21 15:02:10 INFO [app] worker started",
        "db01": "2026-09-21 15:00:00 INFO [postgres] checkpoint complete\n2026-09-21 15:05:00 WARN [postgres] high memory usage",
        "esxi01": "2026-09-21 14:59:00 CRIT [hostd] heartbeat timeout - host uncommunicative",
    },
}


# ============================================================================
# 1. TOOLS: Executable capabilities model can invoke (with side effects or queries)
# ============================================================================

@mcp.tool()
def get_host_status(host: str) -> str:
    """Query current status, IP, and role of a specific homelab host."""
    info = HOMELAB_STORE["hosts"].get(host)
    if not info:
        return json.dumps({"error": f"Host '{host}' not found"})
    return json.dumps({"host": host, **info})


@mcp.tool()
def reboot_host(host: str, force: bool = False) -> str:
    """Simulate rebooting a homelab host (demonstrates an operational action tool)."""
    info = HOMELAB_STORE["hosts"].get(host)
    if not info:
        return json.dumps({"error": f"Cannot reboot: host '{host}' not found"})
    return json.dumps({
        "action": "reboot",
        "host": host,
        "force": force,
        "status": "reboot_initiated",
        "message": f"Host {host} is rebooting (forced={force})"
    })


# ============================================================================
# 2. RESOURCES: Structured contextual data / files model can read (read-only)
# ============================================================================

@mcp.resource("homelab://topology")
def get_topology() -> str:
    """Read full homelab network topology and host inventory."""
    return json.dumps({
        "datacenter": "homelab-primary",
        "gateway": "192.168.1.1",
        "dns": "1.1.1.1",
        "hosts": HOMELAB_STORE["hosts"],
    }, indent=2)


@mcp.resource("homelab://logs/{host}")
def get_host_logs(host: str) -> str:
    """Read recent system logs for a specific host."""
    log_content = HOMELAB_STORE["logs"].get(host, f"No logs available for host '{host}'")
    return log_content


# ============================================================================
# 3. PROMPTS: Reusable workflow / instruction templates provided by the server
# ============================================================================

@mcp.prompt()
def diagnose_host_prompt(host: str) -> str:
    """Generate a standardized diagnostic instruction prompt for an SRE agent."""
    return (
        f"You are an SRE troubleshooting engineer. Please diagnose host '{host}'.\n"
        f"1. First, read resource `homelab://logs/{host}` to inspect error patterns.\n"
        f"2. Next, call tool `get_host_status(host='{host}')` to check connectivity.\n"
        f"3. Finally, explain the root cause and propose remediation steps."
    )


def main() -> None:
    # Run server via standard stdio transport
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
