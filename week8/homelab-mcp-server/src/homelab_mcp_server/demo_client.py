"""Executable demo client exercising the HomeLab MCP Server via stdio."""

from __future__ import annotations

import asyncio
import json
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

# MCP SDK's stdio_client only inherits a small, fixed allowlist of "safe" env
# vars by default (PATH, HOME, etc.) -- it does NOT forward custom app env
# vars like HOMELAB_MODE/OPENWRT_CONFIG_FILE from the parent shell to the
# spawned server subprocess. Without this, setting $env:HOMELAB_MODE="openwrt"
# before running this demo would silently have no effect (server always sees
# the default "mock" mode). Explicitly forward our own app-specific env vars
# on top of the SDK's safe default set.
_APP_ENV_VARS = (
    "HOMELAB_MODE",
    "OPENWRT_CONFIG_JSON",
    "OPENWRT_CONFIG_FILE",
)


def _build_server_env() -> dict[str, str]:
    env = get_default_environment()
    for key in _APP_ENV_VARS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


async def run_demo() -> None:
    server_env = _build_server_env()
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "--python", "3.12", "-m", "homelab_mcp_server.server"],
        env=server_env,
    )

    mode_label = server_env.get("HOMELAB_MODE", "mock")
    print("=" * 65)
    print(f"HomeLab MCP Server Demo Client (adapter mode: {mode_label})")
    print("=" * 65)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Initialize
            init_res = await session.initialize()
            print(f"\n[1] Connected to Server: {init_res.serverInfo.name} (v{init_res.serverInfo.version})")

            # 2. List tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"\n[2] Available Tools: {tool_names}")

            # 3. MCP protocol-level connection liveness check
            print("\n[3] Calling session.send_ping() (MCP protocol ping)...")
            await session.send_ping()
            print("Result: protocol ping succeeded (EmptyResult received)")

            # 4. Application-level status tool (optional, custom, not the protocol ping)
            print("\n[4] Calling application tool ping()...")
            ping_res = await session.call_tool("ping", arguments={})
            ping_text = "".join(c.text for c in ping_res.content if hasattr(c, "text"))
            print(f"Result:\n{ping_text}")

            # 5. Call list_devices_and_services
            print("\n[5] Calling list_devices_and_services(category='database')...")
            inv_res = await session.call_tool("list_devices_and_services", arguments={"category": "database"})
            inv_text = "".join(c.text for c in inv_res.content if hasattr(c, "text"))
            print(f"Result:\n{inv_text}")

            # 6. Call get_health_status
            print("\n[6] Calling get_health_status(target_id='hypervisor-esxi')...")
            health_res = await session.call_tool("get_health_status", arguments={"target_id": "hypervisor-esxi"})
            health_text = "".join(c.text for c in health_res.content if hasattr(c, "text"))
            print(f"Result:\n{health_text}")

            # 7. Call get_basic_metrics
            print("\n[7] Calling get_basic_metrics(target_id='hypervisor-esxi')...")
            metrics_res = await session.call_tool("get_basic_metrics", arguments={"target_id": "hypervisor-esxi"})
            metrics_text = "".join(c.text for c in metrics_res.content if hasattr(c, "text"))
            print(f"Result:\n{metrics_text}")

    print("\n" + "=" * 65)
    print("Demo completed successfully!")
    print("=" * 65)


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
