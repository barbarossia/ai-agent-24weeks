"""The end-to-end function-calling loop: one request, at most one tool call.

    User question
         |
         v
    1. Model request      (mock_model.MockModel.request, given tool definitions)
         |
         v
    2. Tool call decision  (ToolCall(name, arguments) or plain content)
         |
         v
    3. Tool execution      (tools.Tool.execute: validate args -> run mock backend)
         |
         v
    4. Tool result / error returned to the model
         |
         v
    5. Final answer        (mock_model.MockModel.respond_with_tool_result)

This intentionally stops after one tool round-trip. A multi-step ReAct-style
loop (observe -> decide -> act -> repeat) is the subject of Week 5 and is out
of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError

from .mock_model import MockModel
from .tools import TOOLS, ToolExecutionError


@dataclass
class LoopTrace:
    """A record of every step, so the loop's behavior is easy to print/inspect."""

    user_question: str
    tool_definitions: list[dict[str, Any]]
    tool_call_name: Optional[str] = None
    tool_call_arguments: Optional[dict[str, Any]] = None
    tool_result: Optional[dict[str, Any]] = None
    tool_error: Optional[str] = None
    final_answer: str = ""
    steps: list[str] = field(default_factory=list)


def run_once(question: str, model: Optional[MockModel] = None) -> LoopTrace:
    """Run exactly one function-calling round for a single user question."""
    model = model or MockModel()
    tool_definitions = [tool.definition() for tool in TOOLS.values()]
    trace = LoopTrace(user_question=question, tool_definitions=tool_definitions)
    trace.steps.append("1. model request (question + tool definitions sent to model)")

    response = model.request(question, tool_definitions=trace.tool_definitions)

    if response.tool_call is None:
        trace.steps.append("2. model responded directly (no tool needed)")
        trace.final_answer = response.content or ""
        return trace

    trace.tool_call_name = response.tool_call.name
    trace.tool_call_arguments = response.tool_call.arguments
    trace.steps.append(
        f"2. model chose tool call: {response.tool_call.name}({response.tool_call.arguments})"
    )

    tool = TOOLS.get(response.tool_call.name)
    error_message: Optional[str] = None
    result: Optional[dict[str, Any]] = None

    if tool is None:
        error_message = f"unknown tool requested by model: {response.tool_call.name!r}"
        trace.steps.append(
            f"3. tool execution attempted: unknown tool {response.tool_call.name!r} is not registered"
        )
    else:
        trace.steps.append("3. tool execution (arguments validated, then tool runs)")
        try:
            result = tool.execute(response.tool_call.arguments)
        except ValidationError as exc:
            # Bad arguments never reach the mock backend; the loop keeps running.
            error_message = f"invalid arguments: {exc.errors()[0]['msg']}"
        except ToolExecutionError as exc:
            # A valid-but-unsatisfiable request (e.g. unknown host); still no crash.
            error_message = str(exc)

    trace.tool_result = result
    trace.tool_error = error_message
    trace.steps.append(
        "4. tool result returned to model: " + ("error -> " + error_message if error_message else str(result))
    )

    trace.final_answer = model.respond_with_tool_result(
        user_question=question,
        tool_name=response.tool_call.name,
        result=result,
        error=error_message,
    )
    trace.steps.append("5. model produced final answer from the tool result")
    return trace


__all__ = ["run_once", "LoopTrace"]
