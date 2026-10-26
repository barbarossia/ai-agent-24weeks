from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import AgentCard, AgentInterface, Role, SendMessageRequest
from google.protobuf.json_format import MessageToDict
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


@pytest.mark.parametrize("mode", [[], {}])
def test_non_string_mode_returns_typed_failed_task_with_trace(mode):
    with AgentServices() as services:
        trace_id = "trace-week22-invalid-mode"
        _, events = asyncio.run(discover_and_send(
            services.coordinator_url,
            {"mode": mode},
            trace_id=trace_id,
        ))
        task_id, states, result = summarize_task_stream(events)

    assert task_id
    assert states == ["submitted", "working", "failed"]
    assert result["outcome"] == "failure"
    assert result["error"] == "invalid_mode"
    assert result["error_type"] == "invalid_request"
    assert result["tasks"]["coordinator"]["state"] == "failed"
    assert result["trace_id"] == trace_id
    assert all(event["trace_id"] == trace_id for event in result["trace"])
    assert any(event["name"] == "request.rejected" for event in result["trace"])
    assert any(event["name"] == "task.failed" for event in result["trace"])


def _unsafe_agent_card() -> AgentCard:
    return AgentCard(
        name="Synthetic card with an unsafe secondary interface",
        supported_interfaces=[
            AgentInterface(
                url="http://127.0.0.1:12345/a2a",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
            AgentInterface(
                url="https://example.invalid/a2a",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
        ],
    )


def _mock_agent_card_requests(monkeypatch, card: AgentCard):
    requests: list[httpx.Request] = []
    card_json = MessageToDict(card, preserving_proto_field_name=False)
    real_async_client = httpx.AsyncClient
    mock_transport = httpx.MockTransport

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=card_json)

    def async_client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = mock_transport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", async_client_with_mock_transport)
    return requests, real_async_client


def test_discover_and_send_rejects_unsafe_supported_interface_before_post(monkeypatch):
    requests, _ = _mock_agent_card_requests(monkeypatch, _unsafe_agent_card())

    with pytest.raises(ValueError, match="loopback boundary"):
        asyncio.run(discover_and_send(
            "http://127.0.0.1:12345",
            {"mode": "success"},
            trace_id="trace-week22-unsafe-card-client",
        ))

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "http://127.0.0.1:12345/.well-known/agent-card.json"


def test_coordinator_rejects_unsafe_supported_interface_with_task_trace(monkeypatch):
    requests, real_async_client = _mock_agent_card_requests(
        monkeypatch, _unsafe_agent_card()
    )
    coordinator_url = "http://127.0.0.1:18001"
    app = build_app(
        "coordinator",
        coordinator_url,
        specialist_url="http://127.0.0.1:12345",
    )

    async def send_to_coordinator():
        async with real_async_client(
            transport=httpx.ASGITransport(app=app),
            base_url=coordinator_url,
            timeout=2,
            trust_env=False,
        ) as http_client:
            card = await A2ACardResolver(http_client, coordinator_url).get_agent_card()
            client = await create_client(
                agent=card,
                client_config=ClientConfig(streaming=True, httpx_client=http_client),
            )
            request = SendMessageRequest(
                message=new_text_message(
                    '{"mode":"success"}', role=Role.ROLE_USER
                ),
                metadata={"trace_id": "trace-week22-unsafe-card-coordinator"},
            )
            events = [event async for event in client.send_message(request)]
            await client.close()
        return summarize_task_stream(events)

    task_id, states, result = asyncio.run(send_to_coordinator())

    assert task_id
    assert states == ["submitted", "working", "failed"]
    assert result["error"] == "remote_endpoint_not_allowed"
    assert result["tasks"]["coordinator"]["state"] == "failed"
    assert any(event["name"] == "agent_card.rejected" for event in result["trace"])
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "http://127.0.0.1:12345/.well-known/agent-card.json"


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
