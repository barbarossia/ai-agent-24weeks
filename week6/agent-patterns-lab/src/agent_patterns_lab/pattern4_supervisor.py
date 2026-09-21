"""Pattern 4: Supervisor-Worker (监督者-子 Agent).

Applicability:
- Complex multi-faceted tasks requiring task decomposition, parallel or multi-agent delegation, and synthesis.
- Sub-agents maintain isolated scope and tools; Supervisor manages state, assignment, and final aggregation.

Anti-pattern:
- Over-engineering simple tasks with a supervisor + multiple sub-agents (high latency, token waste, failure cascading).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .common import ExecutionTrace, HOMELAB_DATA


class DiagnosticWorker:
    """Worker 1: Specialized in probing infrastructure metrics."""

    def execute_subtask(self, host: str) -> Dict[str, Any]:
        info = HOMELAB_DATA["hosts"].get(host, {"status": "unknown"})
        containers = HOMELAB_DATA["containers"].get(host, [])
        return {
            "worker": "DiagnosticWorker",
            "host": host,
            "status": info.get("status"),
            "cpu_percent": info.get("cpu_percent", 0),
            "container_count": len(containers),
        }


class PolicyAuditWorker:
    """Worker 2: Specialized in policy and compliance rules (e.g. SRE limits)."""

    def execute_subtask(self, diagnostic_result: Dict[str, Any]) -> Dict[str, Any]:
        violations = []
        if diagnostic_result.get("status") != "up":
            violations.append("CRITICAL: Host is offline")
        if diagnostic_result.get("cpu_percent", 0) > 85:
            violations.append("WARNING: CPU usage exceeds 85% policy limit")
        if diagnostic_result.get("container_count", 0) == 0 and diagnostic_result.get("status") == "up":
            violations.append("INFO: No workload containers running on active host")

        return {
            "worker": "PolicyAuditWorker",
            "host": diagnostic_result.get("host"),
            "passed": len(violations) == 0,
            "violations": violations,
        }


class SupervisorAgent:
    """Supervisor coordinates sub-agents:

    1. Decomposes multi-host audit request into sub-tasks.
    2. Dispatches DiagnosticWorker to inspect hardware & workloads.
    3. Dispatches PolicyAuditWorker to audit results against rules.
    4. Synthesizes a consolidated SRE audit report.
    """

    def __init__(self) -> None:
        self.diagnostic_worker = DiagnosticWorker()
        self.policy_worker = PolicyAuditWorker()

    def run(self, target_hosts: List[str]) -> ExecutionTrace:
        trace = ExecutionTrace(
            pattern_name="4. Supervisor-Worker",
            input_text=f"Supervisor comprehensive SRE audit for hosts: {target_hosts}",
        )
        trace.log(f"Supervisor received audit target list: {target_hosts}")

        consolidated_findings = []

        for host in target_hosts:
            trace.log(f"[Supervisor] Planning subtasks for host '{host}'")

            # 1. Dispatch diagnostic worker
            diag = self.diagnostic_worker.execute_subtask(host)
            trace.log(
                f"[Supervisor -> DiagnosticWorker] Result for {host}: status={diag['status']}, cpu={diag['cpu_percent']}%, containers={diag['container_count']}"
            )

            # 2. Dispatch policy audit worker
            audit = self.policy_worker.execute_subtask(diag)
            trace.log(
                f"[Supervisor -> PolicyAuditWorker] Audit for {host}: passed={audit['passed']}, violations={audit['violations']}"
            )

            consolidated_findings.append({"diag": diag, "audit": audit})

        # 3. Supervisor synthesizes final report
        trace.log("[Supervisor] Synthesizing final multi-agent evaluation")
        lines = ["=== Supervisor Multi-Agent Audit Summary ==="]
        for item in consolidated_findings:
            d = item["diag"]
            a = item["audit"]
            status_symbol = "PASS" if a["passed"] else "FAIL"
            lines.append(f"* Host {d['host']} [{status_symbol}]: status={d['status']}, cpu={d['cpu_percent']}%")
            if a["violations"]:
                for v in a["violations"]:
                    lines.append(f"    - {v}")

        trace.output = "\n".join(lines)
        trace.log("[Supervisor] Audit complete.")
        return trace


def main() -> None:
    supervisor = SupervisorAgent()
    targets = ["web01", "db01", "esxi01"]
    print("=== Pattern 4: Supervisor-Worker ===")
    trace = supervisor.run(targets)
    print(f"\n[Input]: {trace.input_text}")
    for s in trace.steps:
        print(f"  -> {s}")
    print(f"\n[Output]:\n{trace.output}")


if __name__ == "__main__":
    main()
