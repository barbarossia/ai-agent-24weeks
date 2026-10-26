"""Deterministic agent executors used by the local A2A services."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Role, SendMessageRequest, Task, TaskState, TaskStatus
from a2a.utils.errors import A2AError

from .urls import require_loopback_http_url


def _trace_event(
    *, trace_id: str, service: str, name: str, span_id: str,
    parent_span_id: str | None, message_id: str = "", task_id: str = "",
    state: str = "",
) -> dict[str, str]:
    event = {
        "trace_id": trace_id,
        "service": service,
        "name": name,
        "span_id": span_id,
        "parent_span_id": parent_span_id or "",
        "message_id": message_id,
    }
    if task_id:
        event["task_id"] = task_id
    if state:
        event["state"] = state
    return event


def _json_part(value: dict[str, Any]):
    return new_text_part(json.dumps(value, sort_keys=True), media_type="application/json")


def _string_metadata(metadata, key: str) -> str:
    value = metadata.fields.get(key)
    if value is None or value.WhichOneof("kind") != "string_value":
        return ""
    return value.string_value


def _agent_trace_from_metadata(
    metadata, *, trace_id: str, message_id: str, task_id: str, state: str = "",
) -> dict[str, str] | None:
    span_id = _string_metadata(metadata, "span_id")
    if not span_id:
        return None
    name = {
        "specialist.receive": "message.received",
        "specialist.working": "task.working",
        "specialist.artifact": "artifact.created",
        "specialist.complete": "task.completed",
        "specialist.failed": "task.failed",
    }.get(span_id, "task.status")
    return _trace_event(
        trace_id=_string_metadata(metadata, "trace_id") or trace_id,
        service="specialist",
        name=name,
        span_id=span_id,
        parent_span_id=_string_metadata(metadata, "parent_span_id"),
        message_id=message_id,
        task_id=task_id,
        state=state,
    )


async def _enqueue_initial_task(
    context: RequestContext, event_queue: EventQueue, *, metadata: dict[str, Any] | None = None,
) -> None:
    task = Task(
        id=cast(str, context.task_id),
        context_id=cast(str, context.context_id),
        status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
        metadata=metadata,
    )
    if context.message:
        task.history.append(context.message)
    await event_queue.enqueue_event(task)


class SpecialistExecutor(AgentExecutor):
    """Returns synthetic results and trace events for the coordinator."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        metadata = context.metadata
        trace_id = str(metadata.get("trace_id", "trace-unspecified"))
        parent_span_id = str(metadata.get("parent_span_id", "coordinator.dispatch"))
        receive_span = "specialist.receive"
        message_id = context.message.message_id if context.message else ""
        trace = [
            _trace_event(
                trace_id=trace_id,
                service="specialist",
                name="message.received",
                span_id=receive_span,
                parent_span_id=parent_span_id,
                message_id=message_id,
                task_id=cast(str, context.task_id),
            )
        ]
        updater = TaskUpdater(
            event_queue,
            cast(str, context.task_id),
            cast(str, context.context_id),
        )
        trace_metadata = {
            "trace_id": trace_id,
            "span_id": "specialist.working",
            "parent_span_id": receive_span,
        }
        await _enqueue_initial_task(context, event_queue, metadata={
            "trace_id": trace_id,
            "span_id": receive_span,
            "parent_span_id": parent_span_id,
        })
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=new_text_message("Synthetic specialist started.", role=Role.ROLE_AGENT),
            metadata=trace_metadata,
        )
        trace.append(_trace_event(
            trace_id=trace_id,
            service="specialist",
            name="task.working",
            span_id="specialist.working",
            parent_span_id=receive_span,
            message_id=message_id,
            task_id=cast(str, context.task_id),
        ))

        try:
            request = json.loads(context.get_user_input())
        except json.JSONDecodeError:
            request = {}
        mode = request.get("mode", "success") if isinstance(request, dict) else "success"

        if mode == "slow":
            await asyncio.sleep(0.3)

        if mode == "remote_failure":
            result = {"outcome": "failure", "error": "synthetic_remote_failure"}
            trace.append(_trace_event(
                trace_id=trace_id,
                service="specialist",
                name="artifact.created",
                span_id="specialist.artifact",
                parent_span_id="specialist.working",
                message_id=message_id,
                task_id=cast(str, context.task_id),
            ))
            result["trace"] = trace
            await updater.add_artifact(
                parts=[_json_part(result)],
                name="specialist-result",
                metadata={
                    "trace_id": trace_id,
                    "span_id": "specialist.artifact",
                    "parent_span_id": "specialist.working",
                },
            )
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=new_text_message("Synthetic remote failure.", role=Role.ROLE_AGENT),
                metadata={
                    "trace_id": trace_id,
                    "span_id": "specialist.failed",
                    "parent_span_id": "specialist.artifact",
                },
            )
            return

        result = {
            "outcome": "success",
            "summary": "Synthetic checks passed for sample-a and sample-b.",
            "checked_items": ["sample-a", "sample-b"],
        }
        trace.append(_trace_event(
            trace_id=trace_id,
            service="specialist",
            name="artifact.created",
            span_id="specialist.artifact",
            parent_span_id="specialist.working",
            message_id=message_id,
            task_id=cast(str, context.task_id),
        ))
        result["trace"] = trace
        await updater.add_artifact(
            parts=[_json_part(result)],
            name="specialist-result",
            metadata={
                "trace_id": trace_id,
                "span_id": "specialist.artifact",
                "parent_span_id": "specialist.working",
            },
        )
        await updater.update_status(
            TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Synthetic specialist completed.", role=Role.ROLE_AGENT),
            metadata={
                "trace_id": trace_id,
                "span_id": "specialist.complete",
                "parent_span_id": "specialist.artifact",
            },
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id and context.context_id:
            await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def task_state_name(state: int) -> str:
    return TaskState.Name(state).removeprefix("TASK_STATE_").lower()


@dataclass
class RemoteObservation:
    task_id: str = ""
    states: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)
    trace: list[dict[str, str]] = field(default_factory=list)


REMOTE_TIMEOUT_SECONDS = 0.15


async def _call_specialist(
    *,
    specialist_url: str,
    mode: str,
    trace_id: str,
    parent_span_id: str,
    observation: RemoteObservation,
    trace: list[dict[str, str]],
    coordinator_task_id: str,
) -> None:
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as http_client:
        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="agent_card.requested",
            span_id="coordinator.discovery",
            parent_span_id="coordinator.receive",
            task_id=coordinator_task_id,
        ))
        card = await A2ACardResolver(http_client, specialist_url).get_agent_card()
        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="agent_card.discovered",
            span_id="coordinator.discovery.complete",
            parent_span_id="coordinator.discovery",
            task_id=coordinator_task_id,
        ))

        client = await create_client(
            agent=card,
            client_config=ClientConfig(streaming=True, httpx_client=http_client),
        )
        message = new_text_message(
            json.dumps({"mode": mode}, sort_keys=True), role=Role.ROLE_USER
        )
        request = SendMessageRequest(
            message=message,
            metadata={
                "trace_id": trace_id,
                "parent_span_id": parent_span_id,
                "coordinator_task_id": coordinator_task_id,
            },
        )
        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="message.sent",
            span_id=parent_span_id,
            parent_span_id="coordinator.receive",
            message_id=message.message_id,
            task_id=coordinator_task_id,
        ))
        try:
            async for event in client.send_message(request):
                payload = event.WhichOneof("payload")
                if payload == "task":
                    observation.task_id = event.task.id
                    state = task_state_name(event.task.status.state)
                    if not observation.states or observation.states[-1] != state:
                        observation.states.append(state)
                    remote_trace = _agent_trace_from_metadata(
                        event.task.metadata,
                        trace_id=trace_id,
                        message_id=(event.task.history[-1].message_id if event.task.history else ""),
                        task_id=event.task.id,
                    )
                    if remote_trace:
                        observation.trace.append(remote_trace)
                    observation.trace.append(_trace_event(
                        trace_id=trace_id,
                        service="coordinator",
                        name="remote_task.observed",
                        span_id=f"coordinator.observe.{state}",
                        parent_span_id=parent_span_id,
                        task_id=event.task.id,
                        message_id=(event.task.history[-1].message_id if event.task.history else ""),
                        state=state,
                    ))
                elif payload == "status_update":
                    update = event.status_update
                    state = task_state_name(update.status.state)
                    if not observation.task_id:
                        observation.task_id = update.task_id
                    if not observation.states or observation.states[-1] != state:
                        observation.states.append(state)
                    if update.status.HasField("message"):
                        status_message = update.status.message
                        observation.messages.append({
                            "message_id": status_message.message_id,
                            "role": Role.Name(status_message.role).lower(),
                            "state": state,
                            "text": "\n".join(part.text for part in status_message.parts if part.text),
                            "service": "specialist",
                        })
                    status_message_id = (
                        update.status.message.message_id
                        if update.status.HasField("message")
                        else ""
                    )
                    remote_trace = _agent_trace_from_metadata(
                        update.metadata,
                        trace_id=trace_id,
                        message_id=status_message_id,
                        task_id=update.task_id,
                        state=state,
                    )
                    if remote_trace:
                        observation.trace.append(remote_trace)
                    observation.trace.append(_trace_event(
                        trace_id=trace_id,
                        service="coordinator",
                        name="remote_task.status_observed",
                        span_id=f"coordinator.observe.{state}",
                        parent_span_id=parent_span_id,
                        message_id=status_message_id,
                        task_id=update.task_id,
                        state=state,
                    ))
                elif payload == "artifact_update":
                    artifact = event.artifact_update.artifact
                    text = "\n".join(part.text for part in artifact.parts if part.text)
                    try:
                        observation.artifacts.append(json.loads(text))
                    except json.JSONDecodeError:
                        observation.artifacts.append({"outcome": "failure", "error": "invalid_remote_artifact"})
                    remote_trace = _agent_trace_from_metadata(
                        artifact.metadata,
                        trace_id=trace_id,
                        message_id="",
                        task_id=event.artifact_update.task_id,
                    )
                    if remote_trace:
                        observation.trace.append(remote_trace)
                    observation.trace.append(_trace_event(
                        trace_id=trace_id,
                        service="coordinator",
                        name="remote_artifact.received",
                        span_id="coordinator.observe.artifact",
                        parent_span_id=parent_span_id,
                        task_id=event.artifact_update.task_id,
                    ))
        finally:
            await client.close()


class CoordinatorExecutor(AgentExecutor):
    """Discovers the specialist and delegates one bounded A2A task."""

    def __init__(self, specialist_url: str):
        self.specialist_url = require_loopback_http_url(specialist_url)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        metadata = context.metadata
        trace_id = str(metadata.get("trace_id", "trace-unspecified"))
        task_id = cast(str, context.task_id)
        context_id = cast(str, context.context_id)
        incoming = context.message
        incoming_message_id = incoming.message_id if incoming else ""
        trace = [_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="message.received",
            span_id="coordinator.receive",
            parent_span_id=None,
            message_id=incoming_message_id,
            task_id=task_id,
        )]
        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="task.submitted",
            span_id="coordinator.submitted",
            parent_span_id="coordinator.receive",
            task_id=task_id,
            state="submitted",
        ))
        try:
            request = json.loads(context.get_user_input())
        except json.JSONDecodeError:
            request = {}
        mode = request.get("mode", "success") if isinstance(request, dict) else "success"
        if mode not in {"success", "remote_failure", "slow"}:
            mode = "remote_failure"

        updater = TaskUpdater(event_queue, task_id, context_id)
        await _enqueue_initial_task(context, event_queue, metadata={"trace_id": trace_id})
        working_message = new_text_message(
            "Coordinator is discovering a specialist.", role=Role.ROLE_AGENT
        )
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=working_message,
            metadata={"trace_id": trace_id, "span_id": "coordinator.working"},
        )
        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="task.working",
            span_id="coordinator.working",
            parent_span_id="coordinator.submitted",
            message_id=working_message.message_id,
            task_id=task_id,
            state="working",
        ))
        observation = RemoteObservation()
        timed_out = False
        transport_error = ""
        try:
            await asyncio.wait_for(
                _call_specialist(
                    specialist_url=self.specialist_url,
                    mode=mode,
                    trace_id=trace_id,
                    parent_span_id="coordinator.dispatch",
                    observation=observation,
                    trace=trace,
                    coordinator_task_id=task_id,
                ),
                timeout=REMOTE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            timed_out = True
        except (A2AError, httpx.HTTPError) as error:
            transport_error = (
                "remote_protocol_error"
                if isinstance(error, A2AError)
                else "remote_unavailable"
            )

        child_result = observation.artifacts[-1] if observation.artifacts else {}
        trace.extend(observation.trace)

        remote_state = observation.states[-1] if observation.states else "unknown"
        if timed_out:
            outcome = "timeout"
            error = "remote_timeout"
            trace.append(_trace_event(
                trace_id=trace_id,
                service="coordinator",
                name="remote_task.timed_out",
                span_id="coordinator.timeout",
                parent_span_id="coordinator.dispatch",
                task_id=observation.task_id,
                state=remote_state,
            ))
        elif transport_error:
            outcome = "failure"
            error = transport_error
        elif remote_state == "failed" or child_result.get("outcome") != "success":
            outcome = "failure"
            error = str(child_result.get("error", "remote_task_failed"))
        else:
            outcome = "success"
            error = ""

        final_state = (
            TaskState.TASK_STATE_COMPLETED
            if outcome == "success"
            else TaskState.TASK_STATE_FAILED
        )
        final_state_name = task_state_name(final_state)
        sent_event = next((event for event in trace if event["name"] == "message.sent"), None)
        messages = [
            {
                "message_id": incoming_message_id,
                "role": "role_user",
                "state": "received",
                "service": "coordinator",
            },
            {
                "message_id": working_message.message_id,
                "role": "role_agent",
                "state": "working",
                "service": "coordinator",
            },
        ]
        if sent_event:
            messages.append({
                "message_id": sent_event["message_id"],
                "role": "role_user",
                "state": "sent",
                "service": "specialist",
            })
        messages.extend(observation.messages)
        terminal_message_text = (
            "Coordinator completed the delegated task."
            if outcome == "success"
            else f"Coordinator stopped with {error}."
        )
        terminal_message = new_text_message(terminal_message_text, role=Role.ROLE_AGENT)
        messages.append({
            "message_id": terminal_message.message_id,
            "role": "role_agent",
            "state": final_state_name,
            "service": "coordinator",
        })
        result: dict[str, Any] = {
            "trace_id": trace_id,
            "outcome": outcome,
            "tasks": {
                "coordinator": {
                    "task_id": task_id,
                    "state": final_state_name,
                    "states": ["submitted", "working", final_state_name],
                },
                "specialist": {
                    "task_id": observation.task_id,
                    "state": remote_state,
                    "states": observation.states,
                },
            },
            "messages": messages,
        }
        if outcome == "success":
            result["result"] = {
                "summary": child_result.get("summary", ""),
                "checked_items": child_result.get("checked_items", []),
            }
        if child_result:
            result["delegated_artifact"] = {
                key: value for key, value in child_result.items() if key != "trace"
            }
        if outcome != "success":
            result["error"] = error

        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name="artifact.created",
            span_id="coordinator.artifact",
            parent_span_id="coordinator.dispatch",
            task_id=task_id,
            state=final_state_name,
        ))
        trace.append(_trace_event(
            trace_id=trace_id,
            service="coordinator",
            name=f"task.{final_state_name}",
            span_id="coordinator.complete" if outcome == "success" else "coordinator.failed",
            parent_span_id="coordinator.artifact",
            message_id=terminal_message.message_id,
            task_id=task_id,
            state=final_state_name,
        ))
        for sequence, event in enumerate(trace, 1):
            event["sequence"] = str(sequence)
        result["trace"] = trace

        await updater.add_artifact(
            parts=[_json_part(result)],
            name="coordination-result",
            metadata={"trace_id": trace_id, "span_id": "coordinator.artifact"},
        )
        await updater.update_status(
            final_state,
            message=terminal_message,
            metadata={"trace_id": trace_id, "span_id": "coordinator.complete"},
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id and context.context_id:
            await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()
