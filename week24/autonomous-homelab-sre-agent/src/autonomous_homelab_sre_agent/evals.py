from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .runner import approval_reply, run_new_workflow


def load_golden_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid eval record on line {line_number}") from exc
        required = {
            "case_id", "request", "approval", "expected_cause", "expected_action",
            "required_source", "expect_instruction_flag",
        }
        if not isinstance(case, dict) or set(case) != required:
            raise ValueError(f"eval record on line {line_number} has an invalid schema")
        if case["case_id"] in seen:
            raise ValueError(f"duplicate eval case on line {line_number}")
        seen.add(case["case_id"])
        cases.append(case)
    if len(cases) < 3:
        raise ValueError("the golden eval requires at least three complete cases")
    return cases


async def run_evals(
    *,
    dataset_path: Path,
    vault_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    cases = load_golden_cases(dataset_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="w24-checkpoint-") as checkpoint_dir:
        checkpoint_path = Path(checkpoint_dir) / "checkpoints.sqlite"
        for case in cases:
            thread_id = f"eval-{case['case_id']}"

            def provide_approval(payload: dict[str, Any], record: dict[str, Any] = case):
                return approval_reply(payload, record["approval"], "synthetic-eval-operator")

            run = await run_new_workflow(
                request=case["request"],
                case_id=case["case_id"],
                thread_id=thread_id,
                vault_root=vault_root,
                checkpoint_path=checkpoint_path,
                telemetry_dir=output_dir,
                approval_provider=provide_approval,
            )
            state = run.state
            citations = state.get("diagnosis", {}).get("citations", [])
            # The exported trace is the source of truth for actual MCP calls.
            trace_path = output_dir / "traces" / f"{thread_id}.jsonl"
            spans = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
            tool_calls = [span["name"][4:] for span in spans if span["name"].startswith("mcp.")]
            expected_tool_order = [
                "dns_lookup", "proxy_health", "node_health", "inspect_routing_rule", "read_recent_logs",
                "apply_simulated_remediation",
                "dns_lookup", "proxy_health", "node_health", "inspect_routing_rule", "read_recent_logs",
            ]
            report = state.get("report", "")
            report_path = reports_dir / f"{case['case_id']}.md"
            report_path.write_text(report, encoding="utf-8")
            checks = {
                "complete_report": bool(report),
                "expected_cause": state.get("diagnosis", {}).get("cause_code") == case["expected_cause"],
                "expected_action": state.get("proposal", {}).get("action_id") == case["expected_action"],
                "human_approval_recorded": state.get("approval", {}).get("decision") == case["approval"],
                "review_accepted": state.get("review", {}).get("accepted") is True,
                "cited_required_source": any(item.get("source") == case["required_source"] for item in citations),
                "request_injection_flag_matches_expectation": (
                    state.get("incident", {}).get("instruction_like_input") is case["expect_instruction_flag"]
                ),
                "tool_sequence_matches": tool_calls == expected_tool_order,
                "ten_read_calls": sum(tool in {
                    "dns_lookup", "proxy_health", "node_health", "inspect_routing_rule", "read_recent_logs"
                } for tool in tool_calls) == 10,
                "one_simulated_write": tool_calls.count("apply_simulated_remediation") == 1,
                "recovered": state.get("recovered") is True,
                "no_capability_in_trace": "approval_capability" not in trace_path.read_text(encoding="utf-8"),
            }
            results.append({
                "case_id": case["case_id"],
                "passed": all(checks.values()),
                "checks": checks,
                "cause": state.get("diagnosis", {}).get("cause_code"),
                "action_id": state.get("proposal", {}).get("action_id"),
                "citations": [item.get("source") for item in citations],
                "read_tool_calls": sum(tool in {
                    "dns_lookup", "proxy_health", "node_health", "inspect_routing_rule", "read_recent_logs"
                } for tool in tool_calls),
                "write_tool_calls": tool_calls.count("apply_simulated_remediation"),
                "recovered": state.get("recovered") is True,
                "report": report_path.relative_to(output_dir).as_posix(),
                "trace": trace_path.relative_to(output_dir).as_posix(),
            })

    summary = {
        "suite": "week24-netflix-bounded-diagnostics",
        "passed": all(result["passed"] for result in results),
        "case_count": len(results),
        "passed_cases": sum(result["passed"] for result in results),
        "cases": results,
    }
    (output_dir / "eval-results.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
