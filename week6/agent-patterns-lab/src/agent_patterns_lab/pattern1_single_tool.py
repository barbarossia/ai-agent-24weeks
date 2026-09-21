"""Pattern 1: Single Agent with Tool Calling (单 Agent 工具调用).

Applicability:
- Bounded, focused interactive queries where an LLM chooses dynamically between 1-5 tools.
- Low task complexity, single domain context.

Anti-pattern:
- Forcing dozens of diverse domain tools into a single agent (context bloat, confusion, hallucinations).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from .common import ExecutionTrace, HOMELAB_DATA, ToolCall


class SingleAgentWithTools:
    def __init__(self) -> None:
        self.tools = {
            "get_host_status": self._tool_get_host_status,
            "get_docker_status": self._tool_get_docker_status,
        }

    def _tool_get_host_status(self, host: str) -> Dict[str, Any]:
        info = HOMELAB_DATA["hosts"].get(host)
        if not info:
            return {"error": f"Unknown host '{host}'"}
        return {"host": host, **info}

    def _tool_get_docker_status(self, host: str) -> Dict[str, Any]:
        containers = HOMELAB_DATA["containers"].get(host)
        if containers is None:
            return {"error": f"No containers found on host '{host}'"}
        return {"host": host, "containers": containers}

    def _mock_llm_decide(self, question: str) -> ToolCall | str:
        q = question.lower()
        host_match = re.search(r"\b(web01|db01|esxi01)\b", q)
        target_host = host_match.group(1) if host_match else "web01"

        if "docker" in q or "container" in q:
            return ToolCall(name="get_docker_status", arguments={"host": target_host})
        if "host" in q or "status" in q or "server" in q:
            return ToolCall(name="get_host_status", arguments={"host": target_host})

        return f"I can answer host or docker queries for homelab. You asked: {question}"

    def run(self, question: str) -> ExecutionTrace:
        trace = ExecutionTrace(pattern_name="1. Single Agent with Tools", input_text=question)
        trace.log(f"Received user question: '{question}'")

        decision = self._mock_llm_decide(question)
        if isinstance(decision, str):
            trace.log("Agent decided direct answer without tools.")
            trace.output = decision
            return trace

        trace.log(f"Agent chose tool '{decision.name}' with arguments {decision.arguments}")
        tool_fn = self.tools.get(decision.name)
        if not tool_fn:
            result = {"error": f"Tool '{decision.name}' not registered"}
        else:
            result = tool_fn(**decision.arguments)

        trace.log(f"Tool execution returned: {json.dumps(result)}")

        # Format final response
        if "error" in result:
            trace.output = f"Failed to retrieve data: {result['error']}"
        elif decision.name == "get_host_status":
            trace.output = f"Host {result['host']} is {result['status']} (IP: {result['ip']}, CPU: {result['cpu_percent']}%)"
        elif decision.name == "get_docker_status":
            c_names = ", ".join(c["name"] for c in result["containers"])
            trace.output = f"Host {result['host']} has {len(result['containers'])} containers: {c_names}"

        trace.log("Agent generated final answer from tool result.")
        return trace


def main() -> None:
    agent = SingleAgentWithTools()
    questions = [
        "Check status of host web01",
        "List docker containers on db01",
        "What is your name?",
    ]
    print("=== Pattern 1: Single Agent with Tools ===")
    for q in questions:
        trace = agent.run(q)
        print(f"\n[Input]: {trace.input_text}")
        for s in trace.steps:
            print(f"  -> {s}")
        print(f"[Output]: {trace.output}")


if __name__ == "__main__":
    main()
