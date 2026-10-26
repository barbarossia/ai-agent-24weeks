"""Small SDK client helpers shared by the demo and integration tests."""
from __future__ import annotations

import json
from typing import Any

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import (
    AgentCard,
    Role,
    SendMessageRequest,
    StreamResponse,
    TaskState,
)

from .urls import require_loopback_http_url


class UnsafeAgentCardEndpoint(ValueError):
    """An advertised A2A endpoint is outside the lab's loopback boundary."""


def validate_agent_card_endpoints(card: AgentCard) -> AgentCard:
    """Reject a card if any supported interface could direct traffic off-loopback."""
    if not card.supported_interfaces:
        raise UnsafeAgentCardEndpoint("Agent Card advertises no supported interfaces")
    try:
        for interface in card.supported_interfaces:
            require_loopback_http_url(interface.url, allow_path=True)
    except ValueError as error:
        raise UnsafeAgentCardEndpoint(
            "Agent Card advertises an endpoint outside the loopback boundary"
        ) from error
    return card


async def discover_and_send(
    base_url: str,
    payload: dict[str, Any],
    *,
    trace_id: str,
    timeout_seconds: float = 3.0,
) -> tuple[AgentCard, list[StreamResponse]]:
    """Resolve the official Agent Card and stream one JSON text message."""
    base_url = require_loopback_http_url(base_url)
    async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as http_client:
        card = await resolve_agent_card(base_url, http_client)
        client = await create_client(
            agent=card,
            client_config=ClientConfig(streaming=True, httpx_client=http_client),
        )
        message = new_text_message(
            json.dumps(payload, sort_keys=True), role=Role.ROLE_USER
        )
        request = SendMessageRequest(
            message=message,
            metadata={"trace_id": trace_id},
        )
        try:
            events = [event async for event in client.send_message(request)]
        finally:
            await client.close()
    return card, events


async def resolve_agent_card(
    base_url: str, http_client: httpx.AsyncClient | None = None
) -> AgentCard:
    """Resolve a local service's public card through the SDK's well-known URI."""
    base_url = require_loopback_http_url(base_url)
    if http_client is not None:
        card = await A2ACardResolver(http_client, base_url).get_agent_card()
        return validate_agent_card_endpoints(card)
    async with httpx.AsyncClient(timeout=3.0, trust_env=False) as local_client:
        card = await A2ACardResolver(local_client, base_url).get_agent_card()
        return validate_agent_card_endpoints(card)


def summarize_task_stream(
    events: list[StreamResponse],
) -> tuple[str, list[str], dict[str, Any] | None]:
    """Extract the task ID, status transitions, and JSON artifact from SDK events."""
    task_id = ""
    states: list[str] = []
    artifact: dict[str, Any] | None = None
    for event in events:
        payload = event.WhichOneof("payload")
        if payload == "task":
            task_id = event.task.id
            state = TaskState.Name(event.task.status.state).removeprefix("TASK_STATE_").lower()
        elif payload == "status_update":
            task_id = task_id or event.status_update.task_id
            state = TaskState.Name(event.status_update.status.state).removeprefix("TASK_STATE_").lower()
        else:
            state = ""
        if state and (not states or states[-1] != state):
            states.append(state)
        if payload == "artifact_update":
            text = "\n".join(
                part.text for part in event.artifact_update.artifact.parts if part.text
            )
            try:
                artifact = json.loads(text)
            except json.JSONDecodeError:
                artifact = {"outcome": "failure", "error": "invalid_coordinator_artifact"}
    return task_id, states, artifact
