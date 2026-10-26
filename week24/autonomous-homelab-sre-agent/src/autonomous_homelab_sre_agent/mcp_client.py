from __future__ import annotations

import json
import secrets
import sys
from typing import Any, Callable

from mcp import Client, StdioServerParameters

from .models import SimulationResult
from .scenarios import READ_TOOL_ORDER, get_scenario
from .workflow_policy import proposal_digest


READ_TOOL_ARGUMENTS: dict[str, dict[str, Any]] = {
    "dns_lookup": {"domain": "netflix.com"},
    "proxy_health": {"pool": "media-proxy"},
    "node_health": {"service": "netflix"},
    "inspect_routing_rule": {"domain": "netflix.com"},
    "read_recent_logs": {"service": "edge-simulator", "limit": 20},
}
WRITE_TOOL_NAME = "apply_simulated_remediation"
ToolEvent = Callable[[str, str], None]


class MCPBoundaryError(RuntimeError):
    pass


def _tool_payload(result: Any) -> dict[str, Any]:
    if result.is_error:
        details = " ".join(getattr(item, "text", "") for item in result.content)
        raise MCPBoundaryError(details or "MCP tool call failed")
    payload = getattr(result, "structured_content", None)
    if payload is not None:
        if isinstance(payload, dict) and set(payload) == {"result"} and isinstance(payload["result"], dict):
            return payload["result"]
        if isinstance(payload, dict):
            return payload
    text = "".join(getattr(item, "text", "") for item in result.content)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        raise MCPBoundaryError("MCP tool returned an unexpected payload") from None
    if not isinstance(decoded, dict):
        raise MCPBoundaryError("MCP tool returned a non-object payload")
    return decoded


async def read_diagnostics(
    case_id: str,
    *,
    overlay: str | None = None,
    on_tool: ToolEvent | None = None,
) -> dict[str, dict[str, Any]]:
    scenario = get_scenario(case_id)
    environment: dict[str, str] = {}
    if overlay:
        if overlay != scenario.action_id:
            raise MCPBoundaryError("unsupported simulation overlay")
        environment["W24_SIMULATION_OVERLAY"] = overlay
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "autonomous_homelab_sre_agent.mcp_read_server", "--case", scenario.case_id],
        env=environment,
    )
    observations: dict[str, dict[str, Any]] = {}
    async with Client(params) as client:
        tool_list = await client.list_tools()
        discovered = {item.name for item in tool_list.tools}
        if discovered != set(READ_TOOL_ORDER):
            raise MCPBoundaryError("read server tool inventory differs from the read-only contract")
        for name in READ_TOOL_ORDER:
            if on_tool:
                on_tool(name, "started")
            try:
                result = await client.call_tool(name, READ_TOOL_ARGUMENTS[name])
                observations[name] = _tool_payload(result)
            except Exception:
                if on_tool:
                    on_tool(name, "error")
                raise
            if on_tool:
                on_tool(name, "ok")
    return observations


async def apply_simulated_remediation(
    case_id: str,
    *,
    action_id: str,
    digest: str,
    on_tool: ToolEvent | None = None,
) -> dict[str, str]:
    scenario = get_scenario(case_id)
    if action_id != scenario.action_id or digest != proposal_digest(scenario):
        raise MCPBoundaryError("proposal does not match the simulator allowlist")
    # This capability is minted only by the post-approval graph node and never enters graph state.
    capability = secrets.token_urlsafe(32)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "autonomous_homelab_sre_agent.mcp_write_server", "--case", scenario.case_id],
        env={"W24_SIMULATED_WRITE_CAPABILITY": capability},
    )
    async with Client(params) as client:
        tool_list = await client.list_tools()
        discovered = {item.name for item in tool_list.tools}
        if discovered != {WRITE_TOOL_NAME}:
            raise MCPBoundaryError("write server tool inventory differs from the single-tool contract")
        if on_tool:
            on_tool(WRITE_TOOL_NAME, "started")
        try:
            result = await client.call_tool(WRITE_TOOL_NAME, {
                "action_id": action_id,
                "digest": digest,
                "approval_capability": capability,
            })
            payload = _tool_payload(result)
            simulation = SimulationResult.model_validate(payload)
        except Exception:
            if on_tool:
                on_tool(WRITE_TOOL_NAME, "error")
            raise
        if on_tool:
            on_tool(WRITE_TOOL_NAME, "ok")
    return simulation.model_dump(mode="json")


async def call_write_server_without_capability(case_id: str, action_id: str, digest: str) -> dict[str, Any]:
    """Security-test helper; deliberately launches a writer without a capability."""
    scenario = get_scenario(case_id)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "autonomous_homelab_sre_agent.mcp_write_server", "--case", scenario.case_id],
        env={},
    )
    async with Client(params) as client:
        result = await client.call_tool(WRITE_TOOL_NAME, {
            "action_id": action_id,
            "digest": digest,
            "approval_capability": "",
        })
        return {"is_error": result.is_error, "text": " ".join(
            getattr(item, "text", "") for item in result.content
        )}
