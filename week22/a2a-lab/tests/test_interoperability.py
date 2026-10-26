from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from a2a.client import A2ACardResolver
from week22_a2a_lab.agents import REMOTE_TIMEOUT_SECONDS
from week22_a2a_lab.client import discover_and_send, summarize_task_stream
from week22_a2a_lab.runtime import AgentServices
from week22_a2a_lab.server import build_app


def test_independent_services_discover_and_complete_correlated_a2a_flow():
    with AgentServices() as services:
        async def discover_both():
            async with httpx.AsyncClient(timeout=2, trust_env=False) as http_client:
                specialist = await A2ACardResolver(
                    http_client, services.specialist_url
                ).get_agent_card()
                coordinator = await A2ACardResolver(
                    http_client, services.coordinator_url
                ).get_agent_card()
            return specialist, coordinator

        specialist_card, coordinator_card = asyncio.run(discover_both())
        assert specialist_card.name == "Week 22 Synthetic Specialist"
        assert coordinator_card.name == "Week 22 Coordinator"
        assert specialist_card.supported_interfaces[0].protocol_version == "1.0"

        trace_id = "trace-week22-success"
        _, events = asyncio.run(discover_and_send(
            services.coordinator_url, {"mode": "success"}, trace_id=trace_id
        ))
        coordinator_task_id, coordinator_states, result = summarize_task_stream(events)

        assert coordinator_task_id
        assert coordinator_states == ["submitted", "working", "completed"]
        assert result["outcome"] == "success"
        assert result["tasks"]["coordinator"]["task_id"] == coordinator_task_id
        assert result["tasks"]["coordinator"]["state"] == "completed"
        assert result["tasks"]["specialist"]["task_id"]
        assert result["tasks"]["specialist"]["states"] == ["submitted", "working", "completed"]
        assert result["delegated_artifact"]["checked_items"] == ["sample-a", "sample-b"]
        assert [(message["service"], message["state"]) for message in result["messages"][:3]] == [
            ("coordinator", "received"),
            ("coordinator", "working"),
            ("specialist", "sent"),
        ]
        assert all(message["message_id"] for message in result["messages"])

        trace = result["trace"]
        assert all(event["trace_id"] == trace_id for event in trace)
        assert [int(event["sequence"]) for event in trace] == list(range(1, len(trace) + 1))
        sent = next(event for event in trace if event["name"] == "message.sent")
        received = next(event for event in trace if event["name"] == "message.received" and event["service"] == "specialist")
        assert sent["message_id"] == received["message_id"]
        assert any(event["name"] == "agent_card.discovered" for event in trace)
        assert any(event["name"] == "remote_artifact.received" for event in trace)
        assert {
            "message.received",
            "task.working",
            "artifact.created",
            "task.completed",
        } <= {
            event["name"]
            for event in trace
            if event["service"] == "specialist"
        }


def test_remote_task_failure_is_exposed_as_failed_coordinator_task():
    with AgentServices() as services:
        _, events = asyncio.run(discover_and_send(
            services.coordinator_url,
            {"mode": "remote_failure"},
            trace_id="trace-week22-failure",
        ))
        task_id, states, result = summarize_task_stream(events)

    assert task_id
    assert states == ["submitted", "working", "failed"]
    assert result["outcome"] == "failure"
    assert result["error"] == "synthetic_remote_failure"
    assert result["tasks"]["specialist"]["state"] == "failed"
    assert result["delegated_artifact"]["outcome"] == "failure"


def test_slow_remote_task_times_out_within_the_configured_bound():
    with AgentServices() as services:
        started = time.monotonic()
        _, events = asyncio.run(discover_and_send(
            services.coordinator_url,
            {"mode": "slow"},
            trace_id="trace-week22-timeout",
        ))
        elapsed = time.monotonic() - started
        task_id, states, result = summarize_task_stream(events)

    assert task_id
    assert elapsed < 0.8
    assert REMOTE_TIMEOUT_SECONDS == 0.15
    assert states == ["submitted", "working", "failed"]
    assert result["outcome"] == "timeout"
    assert result["error"] == "remote_timeout"
    assert result["tasks"]["specialist"]["states"][:2] == ["submitted", "working"]
    assert any(event["name"] == "remote_task.timed_out" for event in result["trace"])
    assert any(
        event["service"] == "specialist" and event["name"] == "task.working"
        for event in result["trace"]
    )


def test_client_refuses_non_loopback_urls_without_opening_a_connection():
    with pytest.raises(ValueError, match="127.0.0.1"):
        asyncio.run(discover_and_send(
            "http://example.org", {"mode": "success"}, trace_id="trace-no-network"
        ))
    with pytest.raises(ValueError, match="127.0.0.1"):
        build_app("specialist", "http://example.org:8000")
    with pytest.raises(ValueError, match="127.0.0.1"):
        build_app(
            "coordinator",
            "http://127.0.0.1:8001",
            specialist_url="http://example.org:8000",
        )
