"""Command-line demo for the Week 5 hand-written Agent Loop."""

from __future__ import annotations

import json
import sys

from .agent_loop import AgentTrace, StopReason, run_agent
from .react_model import StubbornModel

DEMO_QUESTIONS = [
    "Diagnose host web01",  # up -> checks docker + alerts -> 3-step final diagnosis
    "Diagnose host esxi01",  # down -> stops early after 1 step
    "Diagnose host buggy01",  # alerting tool crashes unexpectedly -> handled, still finishes
    "What is the status of host db01?",  # single-tool question (Week 4 style), 1 step
    "Tell me a joke",  # no tool needed, 0 steps
]


def _print_trace(trace: AgentTrace) -> None:
    print(f"\n=== Question: {trace.question}")
    for step in trace.steps:
        line = f"  step {step.step_number}: {step.thought}"
        if step.action:
            line += f" | action={step.action}({step.action_input})"
            if step.error is not None:
                line += f" -> ERROR: {step.error}"
            else:
                line += f" -> observation: {step.result}"
        print(line)
    print(f"  stop_reason: {trace.stop_reason.value} | elapsed: {trace.elapsed_seconds:.4f}s")
    if trace.final_answer:
        print(f"  -> Final answer: {trace.final_answer}")


def _run_max_steps_demo() -> None:
    print("\n=== Demo: max_steps guards against an agent that never stops")
    print("    (StubbornModel always re-checks host status, never answers)")
    trace = run_agent("Diagnose host web01", model=StubbornModel(), max_steps=3)
    _print_trace(trace)
    assert trace.stop_reason is StopReason.MAX_STEPS_REACHED
    print("  (max_steps stopped the loop instead of it running forever)")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] in {"-h", "--help"}:
        print(
            "usage: agent-loop-lab [QUESTION]\n"
            "  With no arguments: run the built-in demo questions plus the\n"
            "                     max_steps safety-limit demo.\n"
            "  With a QUESTION argument: run the agent loop once for it.\n"
            "  --schema: print the JSON-Schema tool definitions and exit."
        )
        return 0

    if argv and argv[0] == "--schema":
        from .tools import TOOLS

        print(json.dumps([tool.definition() for tool in TOOLS.values()], indent=2))
        return 0

    if not argv:
        print("Running built-in demo questions (no API key, fully local mock):")
        for question in DEMO_QUESTIONS:
            _print_trace(run_agent(question))
        _run_max_steps_demo()
        return 0

    question = " ".join(argv)
    _print_trace(run_agent(question))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
