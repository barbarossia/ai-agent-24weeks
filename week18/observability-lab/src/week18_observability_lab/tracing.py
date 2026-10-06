"""Small in-memory tracer; span attributes are deliberately allow-listed."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from math import isfinite
from time import perf_counter
from typing import Iterator
import secrets

_ALLOWED = {"component", "operation", "outcome", "attempt", "token_count", "cost_usd", "fault"}
_SPAN_NAMES = {"request", "agent.step", "llm", "tool"}
_VALUES = {
    "component": {"demo", "agent", "llm", "tool"},
    "operation": {"request", "agent_step", "llm", "tool"},
    "outcome": {"success", "error"},
    "fault": {"none", "slow", "failure", "retry"},
}

def _id(n: int) -> str:
    return secrets.token_hex(n)

@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    attributes: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    status: str = "ok"

    def to_dict(self) -> dict:
        return {"name": self.name, "trace_id": self.trace_id, "span_id": self.span_id,
                "parent_span_id": self.parent_span_id, "attributes": dict(self.attributes),
                "duration_ms": self.duration_ms, "status": self.status}

class Tracer:
    def __init__(self):
        self.spans: list[Span] = []
        self._stack: list[Span] = []

    @contextmanager
    def span(self, name: str, **attributes) -> Iterator[Span]:
        if name not in _SPAN_NAMES:
            raise ValueError("span name outside the fixed allow-list")
        safe = {}
        for key, value in attributes.items():
            if key not in _ALLOWED:
                continue
            if key in _VALUES:
                if isinstance(value, str) and value in _VALUES[key]:
                    safe[key] = value
            elif key == "attempt" and type(value) is int and 1 <= value <= 2:
                safe[key] = value
            elif key == "token_count" and type(value) is int and 0 <= value <= 100_000:
                safe[key] = value
            elif key == "cost_usd" and type(value) in (int, float) and isfinite(value) and 0 <= value <= 100:
                safe[key] = value
        parent = self._stack[-1] if self._stack else None
        span = Span(name=name, trace_id=parent.trace_id if parent else _id(16),
                    span_id=_id(8), parent_span_id=parent.span_id if parent else None, attributes=safe)
        self.spans.append(span)
        self._stack.append(span)
        started = perf_counter()
        try:
            yield span
        except Exception:
            span.status = "error"
            span.attributes["outcome"] = "error"
            raise
        finally:
            if span.duration_ms == 0.0:
                span.duration_ms = round((perf_counter() - started) * 1000, 3)
            self._stack.pop()
