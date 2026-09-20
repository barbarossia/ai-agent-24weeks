"""Tool definitions and tool execution for the Week 4 function-calling demo.

Each tool has:
- a Pydantic argument model (validates the arguments the model "chose" before
  the tool ever runs — the same "don't trust model output" boundary from
  Week 3's structured-output validation);
- a plain Python function that executes against small local mock datasets
  (no network access, no real infrastructure);
- a JSON-Schema-shaped "tool definition" dict, the same shape a real
  OpenAI-style ``tools=[...]`` payload would use, so the concept transfers
  directly to a real provider later.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError


class ToolExecutionError(Exception):
    """Raised when a tool's mock backend cannot satisfy the request.

    This is caught by the calling loop (see loop.py) so that a single bad
    tool call becomes a tool-result message instead of crashing the program.
    """


# ---------------------------------------------------------------------------
# Mock "infrastructure" data — stands in for a real HomeLab / monitoring API.
# ---------------------------------------------------------------------------

_HOST_STATUS = {
    "web01": {"status": "up", "latency_ms": 12},
    "db01": {"status": "up", "latency_ms": 34},
    "esxi01": {"status": "down", "latency_ms": None},
}

_DNS_RECORDS = {
    "example.com": {"resolved_ip": "93.184.216.34", "ttl": 300},
    "internal.lab": {"resolved_ip": "10.0.0.5", "ttl": 60},
}

_DOCKER_STATUS = {
    "web01": [{"name": "nginx", "state": "running"}, {"name": "app", "state": "running"}],
    "db01": [{"name": "postgres", "state": "running"}],
}


# ---------------------------------------------------------------------------
# Argument schemas (validated before execution).
# ---------------------------------------------------------------------------


class HostArgs(BaseModel):
    model_config = {"extra": "forbid"}

    host: str = Field(min_length=1, max_length=64, description="Host name, e.g. 'web01'")


class DomainArgs(BaseModel):
    model_config = {"extra": "forbid"}

    domain: str = Field(min_length=1, max_length=253, description="Domain name, e.g. 'example.com'")


# ---------------------------------------------------------------------------
# Tool implementations.
# ---------------------------------------------------------------------------


def get_host_status(host: str) -> dict[str, Any]:
    """Return mock up/down status for a host."""
    record = _HOST_STATUS.get(host)
    if record is None:
        raise ToolExecutionError(f"unknown host: {host!r}")
    return {"host": host, **record}


def get_dns_result(domain: str) -> dict[str, Any]:
    """Return a mock DNS resolution result for a domain."""
    record = _DNS_RECORDS.get(domain)
    if record is None:
        raise ToolExecutionError(f"NXDOMAIN: {domain!r} not found")
    return {"domain": domain, **record}


def get_docker_status(host: str) -> dict[str, Any]:
    """Return mock docker container states for a host."""
    containers = _DOCKER_STATUS.get(host)
    if containers is None:
        raise ToolExecutionError(f"no docker data for host: {host!r}")
    return {"host": host, "containers": containers}


# ---------------------------------------------------------------------------
# Tool registry: name -> (arg model, function, JSON-Schema tool definition).
# ---------------------------------------------------------------------------


class Tool(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[..., dict[str, Any]]

    def definition(self) -> dict[str, Any]:
        """Render an OpenAI-style tool definition (what a real model API sees)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def execute(self, raw_arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments, then run the tool.

        Raises ``ValidationError`` for malformed arguments and
        ``ToolExecutionError`` for a valid-but-unsatisfiable request. Both are
        caught by the loop, never left to crash the process.
        """
        args = self.args_model.model_validate(raw_arguments)
        return self.func(**args.model_dump())


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            name="get_host_status",
            description="Get up/down status and latency for a named host.",
            args_model=HostArgs,
            func=get_host_status,
        ),
        Tool(
            name="get_dns_result",
            description="Resolve a domain name to its mock DNS record.",
            args_model=DomainArgs,
            func=get_dns_result,
        ),
        Tool(
            name="get_docker_status",
            description="Get docker container states for a named host.",
            args_model=HostArgs,
            func=get_docker_status,
        ),
    ]
}


__all__ = [
    "TOOLS",
    "Tool",
    "ToolExecutionError",
    "HostArgs",
    "DomainArgs",
    "get_host_status",
    "get_dns_result",
    "get_docker_status",
    "ValidationError",
]
