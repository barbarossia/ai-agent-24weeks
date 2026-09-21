"""Executable demo client exercising the HomeLab MCP Server via stdio."""

from __future__ import annotations

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_demo() -> None:
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "--python", "3.12", "-m", "homelab_mcp_server.server"],
        env=None,
    )

    print("=" * 65)
    print("HomeLab MCP Server Demo Client (Offline Mock Mode)")
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

            # 3. Connection ping
            print("\n[3] Calling ping()...")
            ping_res = await session.call_tool("ping", arguments={})
            ping_text = "".join(c.text for c in ping_res.content if hasattr(c, "text"))
            print(f"Result:\n{ping_text}")

            # 4. Call list_devices_and_services
            print("\n[4] Calling list_devices_and_services(category='database')...")
            inv_res = await session.call_tool("list_devices_and_services", arguments={"category": "database"})
            inv_text = "".join(c.text for c in inv_res.content if hasattr(c, "text"))
            print(f"Result:\n{inv_text}")

            # 5. Call get_health_status
            print("\n[5] Calling get_health_status(target_id='hypervisor-esxi')...")
            health_res = await session.call_tool("get_health_status", arguments={"target_id": "hypervisor-esxi"})
            health_text = "".join(c.text for c in health_res.content if hasattr(c, "text"))
            print(f"Result:\n{health_text}")

            # 6. Call get_basic_metrics
            print("\n[6] Calling get_basic_metrics(target_id='hypervisor-esxi')...")
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
