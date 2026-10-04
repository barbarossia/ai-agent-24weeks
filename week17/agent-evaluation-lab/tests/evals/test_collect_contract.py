"""T0 + fixed-contract: real ``MockHomeLab.collect()`` over a faked transport."""

import asyncio

import pytest

from homelab_knowledge_agent.errors import IntegrationBlocked
from homelab_knowledge_agent.homelab import MockHomeLab
from week17_agent_evaluation_lab.clock import FROZEN_ISO, freeze_homelab_clock
from week17_agent_evaluation_lab.doubles import RecordingSession, patch_homelab_transport


def _collect(session):
    with patch_homelab_transport(session), freeze_homelab_clock():
        return asyncio.run(MockHomeLab().collect())


def test_real_collect_is_deterministic_and_fixed_contract():
    session1 = RecordingSession()
    first = _collect(session1)
    session2 = RecordingSession()
    second = _collect(session2)

    # Real collect() produced byte-identical envelopes across two runs.
    assert first == second
    # Exactly the hardcoded Week 12 sequence, empty args, in order.
    assert [name for name, _ in session1.calls] == ["ping", "get_health_status"]
    assert [args for _, args in session1.calls] == [{}, {}]
    assert session1.calls == session2.calls
    # Envelope fields are constructed by real collect().
    assert first["adapter"] == "MockAdapter"
    assert first["tool"] == "get_health_status"
    assert first["fetched_at"] == FROZEN_ISO
    assert len(first["data"]) == 5
    assert any(row["id"] == "hypervisor-esxi" and row["status"] == "degraded" for row in first["data"])


@pytest.mark.parametrize(
    "ping",
    [
        {"adapter_mode": "openwrt", "read_only": True},
        {"adapter_mode": "mock", "read_only": False},
        {"adapter_mode": "mock"},
    ],
)
def test_real_collect_blocks_non_mock_or_not_read_only(ping):
    # Week 12's collect() catch-all (homelab.py:44-45) deliberately masks the
    # inner IntegrationBlocked with its redacted outer message; the real guard
    # still fires, so we assert the public (redacted) blocker.
    with pytest.raises(IntegrationBlocked, match="mock MCP request failed"):
        _collect(RecordingSession(ping_payload=ping))


def test_real_collect_blocks_tool_error():
    with pytest.raises(IntegrationBlocked):
        _collect(RecordingSession(ping_is_error=True))
