"""End-to-end integration test validating stdio MCP server interaction."""

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import EmptyResult


@pytest.mark.asyncio
async def test_mcp_server_stdio_interaction():
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "--python", "3.12", "-m", "homelab_mcp_server.server"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. MCP protocol-level connection liveness check (the actual
            #    "ping for the server connect": a PingRequest expecting an
            #    EmptyResult, per the official MCP SDK's ClientSession API).
            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)

            # 2. Verify tools discovery
            tools_list = await session.list_tools()
            tool_names = {t.name for t in tools_list.tools}
            assert "ping" in tool_names
            assert "list_devices_and_services" in tool_names
            assert "get_health_status" in tool_names
            assert "get_basic_metrics" in tool_names

            # 3. Call the optional application-level status tool `ping`
            #    (distinct from the protocol-level send_ping() above).
            ping_res = await session.call_tool("ping", arguments={})
            ping_text = "".join(c.text for c in ping_res.content if hasattr(c, "text"))
            assert "pong" in ping_text
            assert "homelab-service-mcp-server" in ping_text

            # 4. Call list_devices_and_services
            inv_res = await session.call_tool("list_devices_and_services", arguments={"category": "hypervisor"})
            inv_text = "".join(c.text for c in inv_res.content if hasattr(c, "text"))
            assert "hypervisor-esxi" in inv_text

            # 5. Call get_health_status
            health_res = await session.call_tool("get_health_status", arguments={"target_id": "router-openwrt"})
            health_text = "".join(c.text for c in health_res.content if hasattr(c, "text"))
            assert "Main Gateway Router" in health_text
            assert "healthy" in health_text

            # 6. Call get_basic_metrics
            metrics_res = await session.call_tool("get_basic_metrics", arguments={"target_id": "db-postgres"})
            metrics_text = "".join(c.text for c in metrics_res.content if hasattr(c, "text"))
            assert "active_connections" in metrics_text
