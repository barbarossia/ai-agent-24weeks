from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server import MCPServer

from .scenarios import get_scenario


def create_read_server(case_id: str, overlay: str | None = None) -> MCPServer:
    scenario = get_scenario(case_id)
    if overlay and overlay != scenario.action_id:
        raise ValueError("unsupported simulation overlay")
    server = MCPServer("week24-read-only-simulator")

    def snapshot(tool: str) -> dict[str, Any]:
        return scenario.read_result(tool, overlay)

    @server.tool()
    def dns_lookup(domain: str) -> dict[str, Any]:
        """Read the fixture DNS answer for the single supported Netflix domain."""
        if domain != "netflix.com":
            raise ValueError("unsupported fixture domain")
        return snapshot("dns_lookup")

    @server.tool()
    def proxy_health(pool: str) -> dict[str, Any]:
        """Read health for the synthetic media proxy pool."""
        if pool != "media-proxy":
            raise ValueError("unsupported fixture pool")
        return snapshot("proxy_health")

    @server.tool()
    def node_health(service: str) -> dict[str, Any]:
        """Read the active synthetic egress node status."""
        if service != "netflix":
            raise ValueError("unsupported fixture service")
        return snapshot("node_health")

    @server.tool()
    def inspect_routing_rule(domain: str) -> dict[str, Any]:
        """Read the synthetic route selected for Netflix traffic."""
        if domain != "netflix.com":
            raise ValueError("unsupported fixture domain")
        return snapshot("inspect_routing_rule")

    @server.tool()
    def read_recent_logs(service: str, limit: int = 20) -> dict[str, Any]:
        """Read a bounded window of synthetic edge events; never reads host logs."""
        if service != "edge-simulator" or not 1 <= limit <= 20:
            raise ValueError("unsupported fixture log request")
        result = snapshot("read_recent_logs")
        result["events"] = result["events"][:limit]
        return result

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    args = parser.parse_args(argv)
    overlay = os.environ.get("W24_SIMULATION_OVERLAY") or None
    create_read_server(args.case, overlay).run()


if __name__ == "__main__":
    main()
