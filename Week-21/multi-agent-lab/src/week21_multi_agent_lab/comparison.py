"""Explicit comparison assumptions for multi-agent and single-agent designs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import RunResult


class ComparisonDimension(str, Enum):
    ISOLATION = "isolation"
    CONTEXT = "context"
    PERMISSIONS = "permissions"
    PARALLELISM = "parallelism"
    COMPLEXITY = "complexity"
    COST = "cost"


@dataclass(frozen=True)
class ComparisonRow:
    dimension: ComparisonDimension
    supervisor_worker: str
    single_agent_with_tools: str
    assumption: str


def compare_with_single_agent(result: RunResult) -> tuple[ComparisonRow, ...]:
    """Compare the run with one agent invoking the same synthetic read tools."""
    tool_calls = sum(
        1
        for report in result.reports
        for item in report.evidence
        if item.provenance.tool is not None
    )
    worker_count = len(result.reports)
    rows = (
        ComparisonRow(
            ComparisonDimension.ISOLATION,
            "Separate worker instances and evidence records; logical separation only.",
            "One process and one agent state for every tool result.",
            "Neither design creates an OS, container, or security sandbox in this demo.",
        ),
        ComparisonRow(
            ComparisonDimension.CONTEXT,
            "Each worker receives a focused task; the supervisor gets typed summaries and cited evidence.",
            "One agent accumulates DNS, route, container, and log results in one context.",
            "Context describes prompt organization, not measured token counts.",
        ),
        ComparisonRow(
            ComparisonDimension.PERMISSIONS,
            "Each specialist has its own immutable tool allowlist, checked on every call.",
            "The baseline agent needs the union of the tools used for the request.",
            "Both examples are read-only; the multi-agent grants are independently enforced in code.",
        ),
        ComparisonRow(
            ComparisonDimension.PARALLELISM,
            "Network and Docker checks are submitted through a thread pool before evidence correlation.",
            "Tool calls are assumed to run sequentially in one agent loop.",
            "The local fixture reads are tiny; the demo proves fan-out structure, not a speedup.",
        ),
        ComparisonRow(
            ComparisonDimension.COMPLEXITY,
            "Requires routing, worker contracts, handoff validation, provenance, and synthesis.",
            "One control loop and direct tool-result handling.",
            "The comparison holds task and evidence sources constant.",
        ),
        ComparisonRow(
            ComparisonDimension.COST,
            f"$0.00 synthetic spend; supervisor + {worker_count} workers; {tool_calls} tool reads.",
            f"$0.00 synthetic spend; 1 agent; the same {tool_calls} tool reads.",
            "No model/provider is called. Production token and dollar costs are not measured; extra worker and handoff prompts usually add cost.",
        ),
    )
    return rows
