from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest, TaskState


LAB_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


def _start_specialist() -> tuple[subprocess.Popen[bytes], str]:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "week22_a2a_lab.server", "--role", "specialist", "--port", str(port)],
        cwd=LAB_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"specialist exited during startup: {process.returncode}")
        try:
            response = httpx.get(f"{url}/.well-known/agent-card.json", timeout=0.1)
            if response.status_code == 200:
                return process, url
        except httpx.HTTPError:
            pass
        time.sleep(0.02)
    process.terminate()
    process.wait(timeout=2)
    raise TimeoutError("specialist did not publish its Agent Card")


def test_specialist_is_discoverable_and_returns_task_artifact():
    process, base_url = _start_specialist()
    try:
        async def exercise_service():
            async with httpx.AsyncClient(timeout=2, trust_env=False) as http_client:
                card = await A2ACardResolver(http_client, base_url).get_agent_card()
                assert card.name == "Week 22 Synthetic Specialist"
                assert card.supported_interfaces[0].protocol_version == "1.0"
                client = await create_client(
                    agent=card,
                    client_config=ClientConfig(streaming=True, httpx_client=http_client),
                )
                request = SendMessageRequest(
                    message=new_text_message(
                        json.dumps({"mode": "success"}), role=Role.ROLE_USER
                    ),
                    metadata={"trace_id": "trace-test-specialist", "parent_span_id": "test.root"},
                )
                events = []
                async for event in client.send_message(request):
                    events.append(event)
                await client.close()
                return events

        events = asyncio.run(exercise_service())
        payloads = [(event.WhichOneof("payload"), event) for event in events]
        assert any(kind == "task" and event.task.status.state == TaskState.TASK_STATE_SUBMITTED for kind, event in payloads)
        assert any(kind == "status_update" and event.status_update.status.state == TaskState.TASK_STATE_WORKING for kind, event in payloads)
        artifact = next(event.artifact_update.artifact for kind, event in payloads if kind == "artifact_update")
        result = json.loads(artifact.parts[0].text)
        assert result["checked_items"] == ["sample-a", "sample-b"]
        assert result["trace"][0]["trace_id"] == "trace-test-specialist"
        assert any(kind == "status_update" and event.status_update.status.state == TaskState.TASK_STATE_COMPLETED for kind, event in payloads)
    finally:
        process.terminate()
        process.wait(timeout=5)
