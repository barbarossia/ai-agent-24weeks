"""Use only the existing Week 8 stdio server, forced to MockAdapter."""

import asyncio
from datetime import datetime, timezone
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from .errors import IntegrationBlocked


def server_parameters():
    env = get_default_environment()
    for key in list(env):
        if key.upper().startswith(("OPENWRT_", "HOMELAB_")):
            del env[key]
    env["HOMELAB_MODE"] = "mock"
    return StdioServerParameters(command=sys.executable,
        args=["-m", "homelab_mcp_server.server"], env=env)


def decode_result(result):
    if result.isError:
        raise IntegrationBlocked("Week 8 MCP returned a tool error.")
    return json.loads("".join(item.text for item in result.content if item.type == "text"))


class MockHomeLab:
    async def collect(self):
        try:
            async with asyncio.timeout(30):
                async with stdio_client(server_parameters()) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        status = decode_result(await session.call_tool("ping", arguments={}))
                        if status.get("adapter_mode") != "mock" or status.get("read_only") is not True:
                            raise IntegrationBlocked("Week 8 server did not confirm read-only MockAdapter mode.")
                        health = decode_result(await session.call_tool("get_health_status", arguments={}))
                        return {"label": "MCP live data for the current request (MockAdapter; not real devices)",
                                "adapter": "MockAdapter", "tool": "get_health_status",
                                "fetched_at": datetime.now(timezone.utc).isoformat(), "data": health}
        except Exception:
            raise IntegrationBlocked("Week 8 mock MCP request failed; verify the installed local dependency.") from None
