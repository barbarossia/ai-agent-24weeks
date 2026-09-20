"""The hand-written, multi-step Agent Loop — the subject of Week 5.

    User question
         |
         v
    +--> 1. Thought  (react_model.ReactModel.decide, given question + history)
    |         |
    |         v
    |    2. Action?
    |    ├─ yes -> 3. Execute tool -> 4. Observation --+
    |    |                                              |
    |    +----------------------------------------------+  (append to history, loop)
    |
    +--> no -> 5. Final Answer  (stop)

Unlike Week 4's ``loop.run_once`` (exactly one optional tool round-trip),
this loop repeats "decide -> act -> observe" until the model produces a
final answer, or one of two safety limits trips:

- ``max_steps``   — a hard cap on the number of decide/act iterations, so a
                     model that never volunteers a final answer cannot spin
                     forever (see ``StopReason.MAX_STEPS_REACHED``).
- ``timeout_seconds`` — a wall-clock budget for the whole run, checked before
                     every step (see ``StopReason.TIMEOUT``). A ``clock``
                     callable can be injected for deterministic testing
                     instead of sleeping in real time.

Tool execution failures of *any* kind — invalid arguments
(``pydantic.ValidationError``), a known-and-expected failure
(``tools.ToolExecutionError``), or a genuinely unexpected bug in a tool's
implementation (any other ``Exception``) — are all caught here and turned
into an ``Observation`` with ``error`` set, so the loop always continues (or
stops cleanly) instead of crashing the process.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import ValidationError

from .react_model import Decision, Observation, ReactModel
from .tools import TOOLS, ToolExecutionError


class StopReason(str, Enum):
    FINAL_ANSWER = "final_answer"
    MAX_STEPS_REACHED = "max_steps_reached"
    TIMEOUT = "timeout"


@dataclass
class AgentStep:
    """One iteration of the loop, kept for inspection/printing."""

    step_number: int
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class AgentTrace:
    """The full record of a single ``run_agent`` call."""

    question: str
    steps: list[AgentStep]
    final_answer: Optional[str]
    stop_reason: StopReason
    elapsed_seconds: float


def _execute_action(action: str, action_input: dict[str, Any]) -> Observation:
    """Run one tool call, converting every failure mode into an Observation.

    Never raises: a missing tool, invalid arguments, an expected
    ``ToolExecutionError``, and an unexpected bug in the tool itself are all
    turned into ``error`` text so the loop keeps running.
    """
    tool = TOOLS.get(action)
    if tool is None:
        return Observation(action=action, error=f"unknown tool requested by model: {action!r}")

    try:
        result = tool.execute(action_input)
        return Observation(action=action, result=result)
    except ValidationError as exc:
        return Observation(action=action, error=f"invalid arguments: {exc.errors()[0]['msg']}")
    except ToolExecutionError as exc:
        return Observation(action=action, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - deliberately broad: tools must never kill the loop
        return Observation(action=action, error=f"unexpected tool error: {exc}")


def run_agent(
    question: str,
    model: Optional[ReactModel] = None,
    max_steps: int = 6,
    timeout_seconds: float = 10.0,
    clock: Callable[[], float] = time.monotonic,
) -> AgentTrace:
    """Run the ReAct-style loop for one user question until it stops.

    Stops when, in order of priority at the start of each step:
    1. the wall-clock budget (``timeout_seconds``, measured via ``clock``) is
       exhausted -> ``StopReason.TIMEOUT``;
    2. otherwise the model returns a final answer -> ``StopReason.FINAL_ANSWER``;
    3. otherwise, after ``max_steps`` iterations without a final answer
       -> ``StopReason.MAX_STEPS_REACHED``.
    """
    model = model or ReactModel()
    start = clock()
    history: list[Observation] = []
    steps: list[AgentStep] = []

    for step_number in range(1, max_steps + 1):
        elapsed = clock() - start
        if elapsed >= timeout_seconds:
            return AgentTrace(
                question=question,
                steps=steps,
                final_answer=None,
                stop_reason=StopReason.TIMEOUT,
                elapsed_seconds=elapsed,
            )

        decision: Decision = model.decide(question, history)

        if decision.action is None:
            # Final answer (or, for a malformed decision with neither action
            # nor final_answer set, an implicit empty final answer — the loop
            # always terminates rather than trusting the model to be well-formed).
            # No step is recorded here: a final answer is not a tool call, so
            # ``steps`` only ever contains actual action/observation pairs.
            return AgentTrace(
                question=question,
                steps=steps,
                final_answer=decision.final_answer or "",
                stop_reason=StopReason.FINAL_ANSWER,
                elapsed_seconds=clock() - start,
            )

        observation = _execute_action(decision.action, decision.action_input or {})
        steps.append(
            AgentStep(
                step_number=step_number,
                thought=decision.thought,
                action=decision.action,
                action_input=decision.action_input,
                result=observation.result,
                error=observation.error,
            )
        )
        history.append(observation)

    return AgentTrace(
        question=question,
        steps=steps,
        final_answer=None,
        stop_reason=StopReason.MAX_STEPS_REACHED,
        elapsed_seconds=clock() - start,
    )


__all__ = ["run_agent", "AgentStep", "AgentTrace", "StopReason"]
