"""Automated smoke test suite validating MCP Server and Client interaction."""

import pytest
from mcp_fundamentals_lab.client import run_mcp_client_demo


@pytest.mark.asyncio
async def test_mcp_client_server_full_lifecycle():
    results = await run_mcp_client_demo()

    # 1. Server info & protocol handshake
    assert "server_info" in results
    assert results["server_info"]["name"] == "homelab-mcp-server"

    # 2. Tool discovery and execution
    assert "get_host_status" in results["tools_discovered"]
    assert "reboot_host" in results["tools_discovered"]
    assert results["tool_result_web01"]["status"] == "up"
    assert results["tool_result_web01"]["ip"] == "192.168.1.10"
    assert results["tool_result_reboot"]["action"] == "reboot"
    assert results["tool_result_reboot"]["force"] is True

    # 3. Resources read
    assert results["topology_read"] is True
    assert "heartbeat timeout" in results["log_read"]

    # 4. Prompts generation
    assert "diagnose_host_prompt" in results["prompts_discovered"]
    assert any("esxi01" in msg for msg in results["prompt_messages"])
