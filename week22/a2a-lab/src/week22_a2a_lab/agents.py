"""Deterministic agent executors used by the local A2A services."""
from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from a2a.helpers import new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Role, Task, TaskState, TaskStatus


def _trace_event(
    *, trace_id: str, service: str, name: str, span_id: str,
    parent_span_id: str | None, message_id: str = "",
) -> dict[str, str]:
    return {
        "trace_id": trace_id,
        "service": service,
        "name": name,
        "span_id": span_id,
        "parent_span_id": parent_span_id or "",
        "message_id": message_id,
    }


def _json_part(value: dict[str, Any]):
    return new_text_part(json.dumps(value, sort_keys=True), media_type="application/json")


async def _enqueue_initial_task(context: RequestContext, event_queue: EventQueue) -> None:
    task = Task(
        id=cast(str, context.task_id),
        context_id=cast(str, context.context_id),
        status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
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
            )
        ]
        updater = TaskUpdater(
            event_queue,
            cast(str, context.task_id),
            cast(str, context.context_id),
        )
        await _enqueue_initial_task(context, event_queue)
        await updater.start_work(new_text_message("Synthetic specialist started."))
        trace.append(_trace_event(
            trace_id=trace_id,
            service="specialist",
            name="task.working",
            span_id="specialist.working",
            parent_span_id=receive_span,
            message_id=message_id,
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
                name="task.failed",
                span_id="specialist.failed",
                parent_span_id="specialist.working",
                message_id=message_id,
            ))
            result["trace"] = trace
            await updater.add_artifact(
                parts=[_json_part(result)], name="specialist-result"
            )
            await updater.failed(new_text_message("Synthetic remote failure."))
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
        ))
        trace.append(_trace_event(
            trace_id=trace_id,
            service="specialist",
            name="task.completed",
            span_id="specialist.complete",
            parent_span_id="specialist.artifact",
            message_id=message_id,
        ))
        result["trace"] = trace
        await updater.add_artifact(parts=[_json_part(result)], name="specialist-result")
        await updater.complete(new_text_message("Synthetic specialist completed."))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id and context.context_id:
            await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def task_state_name(state: int) -> str:
    return TaskState.Name(state).removeprefix("TASK_STATE_").lower()
