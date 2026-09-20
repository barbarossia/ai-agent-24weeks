"""A deterministic mock "model" that stands in for a real LLM's tool-calling API.

Real providers (OpenAI-style) return either:
  - a message with ``tool_calls: [{name, arguments}]`` asking the caller to run
    a tool and send the result back, or
  - a plain assistant message with ``content`` (no tool needed).

This mock reproduces exactly that response shape using simple, deterministic
keyword/regex rules instead of a real language model. No network access, no
API key, fully reproducible — which is the point of a *mock* provider (see
Week 3's ``MockProvider`` for the same idea applied to structured output).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

_HOST_TOKEN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_-]*\d[a-zA-Z0-9_-]*\b")
_DOMAIN_TOKEN = re.compile(r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}\b")


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelResponse:
    """Mirrors a real chat-completion message: either a tool call or content."""

    tool_call: Optional[ToolCall] = None
    content: Optional[str] = None


@dataclass
class MockModel:
    """Deterministic stand-in for an LLM with tool-calling support."""

    # Track every "request" made to the mock, purely for demo/inspection —
    # a real client would log request/response pairs the same way.
    call_log: list[str] = field(default_factory=list)

    # The full tool-definition payload received by the most recent call to
    # ``request`` — kept around so callers/tests can assert the model was
    # actually given the JSON-Schema definitions, not just tool names.
    last_tool_definitions: list[dict[str, Any]] = field(default_factory=list)

    def request(self, user_question: str, tool_definitions: list[dict[str, Any]]) -> ModelResponse:
        """Step 1+2 of the loop: the model receives the question and the
        available tool definitions (full JSON-Schema ``{"type": "function",
        "function": {...}}`` dicts, exactly what a real ``tools=[...]``
        payload would contain), and decides whether to call a tool.

        The available tool *names* used for routing below are derived from
        the definitions themselves (``tool_definitions[i]["function"]["name"]``)
        rather than being passed separately, so the definitions are the single
        source of truth for what the model can see and choose from.
        """
        self.call_log.append(f"request: {user_question!r}")
        self.last_tool_definitions = tool_definitions
        tool_names = [definition["function"]["name"] for definition in tool_definitions]
        question_lower = user_question.lower()

        domain_match = _DOMAIN_TOKEN.search(user_question)
        host_match = _HOST_TOKEN.search(user_question)

        if "docker" in question_lower and "get_docker_status" in tool_names and host_match:
            return ModelResponse(
                tool_call=ToolCall(name="get_docker_status", arguments={"host": host_match.group(0)})
            )
        if (
            ("dns" in question_lower or "resolve" in question_lower or domain_match)
            and "get_dns_result" in tool_names
            and domain_match
        ):
            return ModelResponse(
                tool_call=ToolCall(name="get_dns_result", arguments={"domain": domain_match.group(0)})
            )
        if (
            ("status" in question_lower or "host" in question_lower or "up" in question_lower)
            and "get_host_status" in tool_names
            and host_match
        ):
            return ModelResponse(
                tool_call=ToolCall(name="get_host_status", arguments={"host": host_match.group(0)})
            )

        return ModelResponse(
            content=(
                "I don't have a tool for that question. Try asking about a host's "
                "status, its docker containers, or DNS resolution for a domain."
            )
        )

    def respond_with_tool_result(
        self,
        user_question: str,
        tool_name: str,
        result: Optional[dict[str, Any]],
        error: Optional[str],
    ) -> str:
        """Step 5 of the loop: the model turns the tool's output back into a
        natural-language answer for the user.
        """
        self.call_log.append(f"tool_result: {tool_name} -> {'error' if error else 'ok'}")

        if error is not None:
            return f"I tried to call {tool_name} but it failed: {error}"

        if tool_name == "get_host_status":
            return (
                f"Host '{result['host']}' is {result['status']}"
                + (f" (latency {result['latency_ms']} ms)." if result.get("latency_ms") is not None else ".")
            )
        if tool_name == "get_dns_result":
            return f"'{result['domain']}' resolves to {result['resolved_ip']} (ttl {result['ttl']}s)."
        if tool_name == "get_docker_status":
            names = ", ".join(f"{c['name']}={c['state']}" for c in result["containers"])
            return f"Docker containers on '{result['host']}': {names}."

        return f"Tool {tool_name} returned: {result}"


__all__ = ["MockModel", "ModelResponse", "ToolCall"]
