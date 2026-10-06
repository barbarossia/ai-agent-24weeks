"""Deterministic local agent simulation. No network, model, MCP, or device calls."""
from __future__ import annotations
from dataclasses import dataclass
from time import perf_counter
from .metrics import Metrics
from .tracing import Tracer

@dataclass(frozen=True)
class FaultPlan:
    mode: str = "none"  # none | slow | failure | retry
    def __post_init__(self):
        if self.mode not in {"none", "slow", "failure", "retry"}:
            raise ValueError("fault mode must be none, slow, failure, or retry")

class DemoAgent:
    def __init__(self, tracer: Tracer | None = None, metrics: Metrics | None = None):
        self.tracer = tracer or Tracer()
        self.metrics = metrics or Metrics()

    def _run_child(self, operation, *, attempt=1, fault="none", tokens=0, cost=0.0):
        # Synthetic latency makes the scenario deterministic and never sleeps.
        latency = {"none": 2.0, "slow": 120.0, "failure": 3.0, "retry": 4.0}.get(fault, 2.0)
        status = "error" if fault == "failure" else "success"
        with self.tracer.span(operation, component=operation, operation=operation, attempt=attempt, fault=fault,
                              outcome=status, token_count=tokens, cost_usd=cost) as span:
            span.duration_ms = latency
            self.metrics.observe(operation, status, latency, tokens=tokens, cost_usd=cost)
            if status == "error": raise RuntimeError("injected deterministic failure")

    def handle(self, *, fault="none") -> dict:
        plan = FaultPlan(fault)
        started = perf_counter()
        status = "success"
        with self.tracer.span("request", component="demo", operation="request") as request:
            try:
                with self.tracer.span("agent.step", component="agent", operation="agent_step") as step:
                    self.metrics.observe("agent_step", "success", 1.0)
                    attempts = 2 if plan.mode == "retry" else 1
                    for attempt in range(1, attempts + 1):
                        llm_fault = "failure" if plan.mode == "failure" or (plan.mode == "retry" and attempt == 1) else ("slow" if plan.mode == "slow" else "none")
                        try:
                            self._run_child("llm", attempt=attempt, fault=llm_fault, tokens=120, cost=0.00024)
                            break
                        except RuntimeError:
                            if plan.mode != "retry" or attempt == attempts: raise
                    self._run_child("tool", fault="none")
                    step.attributes.update({"outcome": "success"})
            except RuntimeError:
                status = "error"
                request.attributes["outcome"] = "error"
                raise
            finally:
                elapsed = {"none": 8.0, "slow": 126.0, "failure": 3.0, "retry": 10.0}[plan.mode]
                request.duration_ms = elapsed
                self.metrics.observe("request", status, elapsed, tokens=120 if status == "success" else 0, cost_usd=0.00024 if status == "success" else 0)
        return {"status": status, "fault": plan.mode, "synthetic_latency_ms": {"none": 8, "slow": 126, "failure": 3, "retry": 10}[plan.mode], "span_count": len(self.tracer.spans)}
