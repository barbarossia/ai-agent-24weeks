from mcp import Client

from autonomous_homelab_sre_agent.mcp_client import (
    WRITE_TOOL_NAME,
    call_write_server_without_capability,
    read_diagnostics,
)
from autonomous_homelab_sre_agent.mcp_read_server import create_read_server
from autonomous_homelab_sre_agent.mcp_write_server import create_write_server
from autonomous_homelab_sre_agent.scenarios import READ_TOOL_ORDER, get_scenario
from autonomous_homelab_sre_agent.workflow_policy import proposal_digest


async def test_stdio_client_calls_exactly_five_read_only_tools_in_order():
    outcomes = []
    before = await read_diagnostics(
        "proxy-rule-mismatch", on_tool=lambda tool, result: outcomes.append((tool, result))
    )
    after = await read_diagnostics(
        "proxy-rule-mismatch", overlay="restore_media_proxy_route"
    )

    assert tuple(before) == READ_TOOL_ORDER
    assert before["inspect_routing_rule"]["action"] == "DIRECT"
    assert after["inspect_routing_rule"]["action"] == "PROXY"
    assert before["read_recent_logs"]["events"][1]["message"] == "[UNTRUSTED LOG TEXT REDACTED]"
    assert [tool for tool, result in outcomes if result == "ok"] == list(READ_TOOL_ORDER)


async def test_read_server_has_no_write_tool_and_bounds_domains():
    server = create_read_server("proxy-rule-mismatch")
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == set(READ_TOOL_ORDER)
        result = await client.call_tool("dns_lookup", {"domain": "example.com"})
        assert result.is_error


async def test_write_server_is_separate_and_requires_capability():
    scenario = get_scenario("proxy-rule-mismatch")
    digest = proposal_digest(scenario)
    denied = await call_write_server_without_capability(
        scenario.case_id, scenario.action_id, digest
    )
    assert denied["is_error"] is True
    assert "capability" in denied["text"]

    server = create_write_server(scenario.case_id, "runtime-approval-capability")
    async with Client(server) as client:
        assert {tool.name for tool in (await client.list_tools()).tools} == {WRITE_TOOL_NAME}
        wrong = await client.call_tool(WRITE_TOOL_NAME, {
            "action_id": "arbitrary_action",
            "digest": digest,
            "approval_capability": "runtime-approval-capability",
        })
        assert wrong.is_error
        applied = await client.call_tool(WRITE_TOOL_NAME, {
            "action_id": scenario.action_id,
            "digest": digest,
            "approval_capability": "runtime-approval-capability",
        })
        repeated = await client.call_tool(WRITE_TOOL_NAME, {
            "action_id": scenario.action_id,
            "digest": digest,
            "approval_capability": "runtime-approval-capability",
        })
        assert applied.is_error is False
        assert repeated.is_error is False
        assert applied.structured_content == repeated.structured_content
