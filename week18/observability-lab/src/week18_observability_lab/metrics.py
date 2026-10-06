"""Prometheus text exposition with explicit, bounded label dimensions."""
from __future__ import annotations
from collections import defaultdict

BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000)
STATUSES = {"success", "error"}
OPS = {"request", "agent_step", "llm", "tool"}

def _labels(operation: str, status: str) -> str:
    if operation not in OPS or status not in STATUSES:
        raise ValueError("metric label outside the fixed allow-list")
    return f'operation="{operation}",status="{status}"'

class Metrics:
    def __init__(self):
        self.requests = defaultdict(int)
        self.errors = defaultdict(int)
        self.latency = defaultdict(list)
        self.tokens = defaultdict(int)
        self.cost = defaultdict(float)

    def observe(self, operation: str, status: str, duration_ms: float, *, tokens: int = 0, cost_usd: float = 0.0):
        labels = _labels(operation, status)
        self.requests[labels] += 1
        if status == "error": self.errors[labels] += 1
        self.latency[labels].append(max(0.0, float(duration_ms)))
        self.tokens[labels] += max(0, int(tokens))
        self.cost[labels] += max(0.0, float(cost_usd))

    def render(self) -> str:
        lines = [
            "# HELP agent_requests_total Completed operations.", "# TYPE agent_requests_total counter",
        ]
        lines += [f"agent_requests_total{{{k}}} {v}" for k, v in sorted(self.requests.items())]
        lines += ["# HELP agent_errors_total Failed operations.", "# TYPE agent_errors_total counter"]
        lines += [f"agent_errors_total{{{k}}} {v}" for k, v in sorted(self.errors.items())]
        lines += ["# HELP agent_operation_duration_ms Operation duration in milliseconds.", "# TYPE agent_operation_duration_ms histogram"]
        for labels, values in sorted(self.latency.items()):
            for bucket in BUCKETS:
                lines.append(f'agent_operation_duration_ms_bucket{{{labels},le="{bucket}"}} {sum(x <= bucket for x in values)}')
            lines.append(f'agent_operation_duration_ms_bucket{{{labels},le="+Inf"}} {len(values)}')
            lines.append(f"agent_operation_duration_ms_sum{{{labels}}} {sum(values):.3f}")
            lines.append(f"agent_operation_duration_ms_count{{{labels}}} {len(values)}")
        lines += ["# HELP agent_tokens_total Synthetic token count.", "# TYPE agent_tokens_total counter"]
        lines += [f"agent_tokens_total{{{k}}} {v}" for k, v in sorted(self.tokens.items())]
        lines += ["# HELP agent_cost_usd_total Synthetic estimated cost in USD.", "# TYPE agent_cost_usd_total counter"]
        lines += [f"agent_cost_usd_total{{{k}}} {v:.6f}" for k, v in sorted(self.cost.items())]
        return "\n".join(lines) + "\n"
