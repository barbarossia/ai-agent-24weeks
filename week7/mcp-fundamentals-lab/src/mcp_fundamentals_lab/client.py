"""Minimal MCP Client demonstrating session lifecycle, tools, resources, and prompts.

Uses stdio transport to spawn and communicate with `mcp_fundamentals_lab.server`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_mcp_client_demo() -> Dict[str, Any]:
    # Configure stdio parameters to launch our server module using uv run
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "--python", "3.12", "-m", "mcp_fundamentals_lab.server"],
        env=None,
    )

    results: Dict[str, Any] = {}

    print("=" * 65)
    print("MCP Fundamentals Demo: Official Python MCP Client <-> Server")
    print("=" * 65)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Initialize MCP Session
            print("\n[Step 1] Initializing MCP Session & Handshake...")
            init_result = await session.initialize()
            print(f"  -> Server Info: {init_result.serverInfo.name} (v{init_result.serverInfo.version})")
            print(f"  -> Protocol Version: {init_result.protocolVersion}")
            results["server_info"] = {
                "name": init_result.serverInfo.name,
                "version": init_result.serverInfo.version,
                "protocol": init_result.protocolVersion,
            }

            # 2. Discover and Call Tools
            print("\n[Step 2] Discovering and Calling Tools...")
            tools_list = await session.list_tools()
            tool_names = [t.name for t in tools_list.tools]
            print(f"  -> Discovered Tools: {tool_names}")
            results["tools_discovered"] = tool_names

            # Call get_host_status tool
            print("  -> Calling tool 'get_host_status(host=\"web01\")'")
            call_res = await session.call_tool("get_host_status", arguments={"host": "web01"})
            tool_output_text = "".join(c.text for c in call_res.content if hasattr(c, "text"))
            print(f"     Tool Response: {tool_output_text}")
            results["tool_result_web01"] = json.loads(tool_output_text)

            # Call reboot_host tool
            print("  -> Calling action tool 'reboot_host(host=\"db01\", force=True)'")
            reboot_res = await session.call_tool("reboot_host", arguments={"host": "db01", "force": True})
            reboot_text = "".join(c.text for c in reboot_res.content if hasattr(c, "text"))
            print(f"     Tool Response: {reboot_text}")
            results["tool_result_reboot"] = json.loads(reboot_text)

            # 3. Discover and Read Resources
            print("\n[Step 3] Discovering and Reading Resources...")
            resources_list = await session.list_resources()
            resource_uris = [str(r.uri) for r in resources_list.resources]
            print(f"  -> Discovered Static Resource URIs: {resource_uris}")
            results["resources_discovered"] = resource_uris

            # Read topology resource
            print("  -> Reading resource 'homelab://topology'...")
            top_res = await session.read_resource("homelab://topology")
            top_content = top_res.contents[0].text if top_res.contents else ""
            print(f"     Resource Content preview: {top_content[:120]}...")
            results["topology_read"] = True

            # Read dynamic logs resource
            print("  -> Reading dynamic resource 'homelab://logs/esxi01'...")
            log_res = await session.read_resource("homelab://logs/esxi01")
            log_content = log_res.contents[0].text if log_res.contents else ""
            print(f"     Log Content: {log_content}")
            results["log_read"] = log_content

            # 4. Discover and Retrieve Prompts
            print("\n[Step 4] Discovering and Retrieving Prompts...")
            prompts_list = await session.list_prompts()
            prompt_names = [p.name for p in prompts_list.prompts]
            print(f"  -> Discovered Prompt Templates: {prompt_names}")
            results["prompts_discovered"] = prompt_names

            print("  -> Generating prompt for 'diagnose_host_prompt(host=\"esxi01\")'...")
            prompt_res = await session.get_prompt("diagnose_host_prompt", arguments={"host": "esxi01"})
            prompt_messages = [
                f"{m.role}: {m.content.text if hasattr(m.content, 'text') else str(m.content)}"
                for m in prompt_res.messages
            ]
            print(f"     Prompt Messages:\n     " + "\n     ".join(prompt_messages))
            results["prompt_messages"] = prompt_messages

    print("\n" + "=" * 65)
    print("MCP Demo execution finished successfully!")
    print("=" * 65)
    return results


def main() -> None:
    asyncio.run(run_mcp_client_demo())


if __name__ == "__main__":
    main()
