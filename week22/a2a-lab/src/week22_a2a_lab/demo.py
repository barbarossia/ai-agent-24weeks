"""Run the two-service A2A interoperability demonstration."""
from __future__ import annotations

import asyncio
import json

from .client import discover_and_send, resolve_agent_card, summarize_task_stream
from .runtime import AgentServices


async def _discover_and_run(services: AgentServices):
    specialist_card = await resolve_agent_card(services.specialist_url)
    coordinator_card, events = await discover_and_send(
        services.coordinator_url,
        {"mode": "success"},
        trace_id="trace-week22-demo",
    )
    return specialist_card, coordinator_card, events


def main() -> int:
    with AgentServices() as services:
        specialist_card, coordinator_card, events = asyncio.run(
            _discover_and_run(services)
        )
        task_id, states, artifact = summarize_task_stream(events)
        payload = {
            "demo": "PASS" if artifact and artifact.get("outcome") == "success" else "FAIL",
            "protocol": "A2A 1.0 JSON-RPC",
            "agents": [coordinator_card.name, specialist_card.name],
            "coordinator_task": {"task_id": task_id, "states": states},
            "artifact": artifact,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["demo"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
