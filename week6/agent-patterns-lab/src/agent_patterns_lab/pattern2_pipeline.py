"""Pattern 2: Sequential Pipeline (顺序流水线).

Applicability:
- Linear, deterministic multi-stage transformations (e.g., Extract -> Transform / Analyze -> Summarize / Format).
- Stable workflows where step ordering is known in advance and each step has a clear input/output schema.

Anti-pattern:
- Forcing non-linear, highly exploratory tasks into a static pipeline; or using a heavy LLM agent loop when a deterministic pipeline suffices.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .common import ExecutionTrace, HOMELAB_DATA


class SequentialPipeline:
    """A 3-stage pipeline:

    Stage 1: Collector (Extracts raw host & container data)
    Stage 2: Analyzer (Evaluates health, CPU thresholds, container states)
    Stage 3: Reporter (Formats actionable executive summary)
    """

    def stage_1_collect(self, host: str, trace: ExecutionTrace) -> Dict[str, Any]:
        trace.log(f"[Stage 1 - Collector] Fetching metrics for host '{host}'")
        host_info = HOMELAB_DATA["hosts"].get(host, {"status": "unknown", "cpu_percent": 0})
        containers = HOMELAB_DATA["containers"].get(host, [])
        data = {
            "host": host,
            "host_status": host_info.get("status"),
            "cpu_percent": host_info.get("cpu_percent", 0),
            "containers": containers,
        }
        trace.log(f"[Stage 1 - Collector] Raw metrics collected: {json.dumps(data)}")
        return data

    def stage_2_analyze(self, raw_data: Dict[str, Any], trace: ExecutionTrace) -> Dict[str, Any]:
        trace.log(f"[Stage 2 - Analyzer] Evaluating operational health for '{raw_data['host']}'")
        warnings = []
        is_healthy = True

        if raw_data["host_status"] != "up":
            warnings.append(f"Host status is {raw_data['host_status']}!")
            is_healthy = False

        if raw_data["cpu_percent"] > 80:
            warnings.append(f"High CPU utilization: {raw_data['cpu_percent']}% > threshold 80%")
            is_healthy = False

        c_count = len(raw_data["containers"])
        if c_count == 0:
            warnings.append("No active containers found")

        analysis = {
            "host": raw_data["host"],
            "healthy": is_healthy,
            "warnings": warnings,
            "container_count": c_count,
            "cpu_percent": raw_data["cpu_percent"],
        }
        trace.log(f"[Stage 2 - Analyzer] Analysis outcome: healthy={is_healthy}, warnings={warnings}")
        return analysis

    def stage_3_report(self, analysis: Dict[str, Any], trace: ExecutionTrace) -> str:
        trace.log("[Stage 3 - Reporter] Synthesizing executive report")
        health_badge = "[OK]" if analysis["healthy"] else "[ATTENTION NEEDED]"
        lines = [
            f"=== Health Report for {analysis['host']} ===",
            f"Overall Status: {health_badge}",
            f"CPU Load: {analysis['cpu_percent']}%",
            f"Containers Tracked: {analysis['container_count']}",
        ]
        if analysis["warnings"]:
            lines.append("Warnings:")
            for w in analysis["warnings"]:
                lines.append(f"  - {w}")
        else:
            lines.append("No operational warnings detected.")

        report = "\n".join(lines)
        trace.log("[Stage 3 - Reporter] Report generation complete.")
        return report

    def run(self, host: str) -> ExecutionTrace:
        trace = ExecutionTrace(pattern_name="2. Sequential Pipeline", input_text=f"Pipeline run for host '{host}'")
        raw = self.stage_1_collect(host, trace)
        analysis = self.stage_2_analyze(raw, trace)
        trace.output = self.stage_3_report(analysis, trace)
        return trace


def main() -> None:
    pipeline = SequentialPipeline()
    targets = ["web01", "db01", "esxi01"]
    print("=== Pattern 2: Sequential Pipeline ===")
    for t in targets:
        trace = pipeline.run(t)
        print(f"\n[Input]: {trace.input_text}")
        for s in trace.steps:
            print(f"  -> {s}")
        print(f"[Output]:\n{trace.output}")


if __name__ == "__main__":
    main()
