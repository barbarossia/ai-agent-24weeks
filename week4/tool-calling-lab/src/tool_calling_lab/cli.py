"""Command-line demo for the Week 4 function-calling loop."""

from __future__ import annotations

import json
import sys

from .loop import run_once

DEMO_QUESTIONS = [
    "What is the status of host web01?",
    "Check docker containers on host db01",
    "Resolve DNS for example.com",
    "What is the status of host gateway99?",  # unknown host -> tool error, no crash
    "Tell me a joke",  # no matching tool -> direct answer
]


def _print_trace(trace) -> None:
    print(f"\n=== Question: {trace.user_question}")
    for step in trace.steps:
        print(f"  {step}")
    print(f"  -> Final answer: {trace.final_answer}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        print("Running built-in demo questions (no API key, fully local mock):")
        for question in DEMO_QUESTIONS:
            _print_trace(run_once(question))
        return 0

    if argv[0] in {"-h", "--help"}:
        print(
            "usage: tool-calling-lab [QUESTION]\n"
            "  With no arguments: run the built-in demo questions.\n"
            "  With a QUESTION argument: run one function-calling round for it.\n"
            "  --schema: print the JSON-Schema tool definitions and exit."
        )
        return 0

    if argv[0] == "--schema":
        from .tools import TOOLS

        print(json.dumps([tool.definition() for tool in TOOLS.values()], indent=2))
        return 0

    question = " ".join(argv)
    _print_trace(run_once(question))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
