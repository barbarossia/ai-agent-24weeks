"""Common domain models and mock LLM primitives for Agent Pattern demonstrations.

Everything uses only Python standard library modules without external dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMMessage:
    role: str  # "system", "user", "assistant", "tool"
    content: str = ""
    tool_calls: Optional[List[ToolCall]] = None


@dataclass
class ExecutionTrace:
    pattern_name: str
    input_text: str
    steps: List[str] = field(default_factory=list)
    output: str = ""

    def log(self, step: str) -> None:
        self.steps.append(step)


# Simple mock dataset representing HomeLab infrastructure
HOMELAB_DATA = {
    "hosts": {
        "web01": {"status": "up", "ip": "192.168.1.10", "cpu_percent": 24},
        "db01": {"status": "up", "ip": "192.168.1.20", "cpu_percent": 88},
        "esxi01": {"status": "down", "ip": "192.168.1.2", "cpu_percent": 0},
    },
    "containers": {
        "web01": [{"name": "nginx", "status": "running"}, {"name": "app", "status": "running"}],
        "db01": [{"name": "postgres", "status": "running"}, {"name": "redis", "status": "running"}],
    },
    "network": {
        "gateway": "192.168.1.1",
        "dns": "1.1.1.1",
        "openwrt_status": "online",
        "vpn_status": "connected",
    },
}
