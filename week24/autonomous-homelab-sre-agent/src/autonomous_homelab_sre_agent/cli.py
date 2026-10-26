from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from .evals import run_evals
from .report import save_report_to_knowledge
from .runner import approval_reply, new_thread_id, resume_workflow, run_new_workflow
from .scenarios import fixture_ids, get_scenario
from .telemetry import TraceRecorder


LAB_ROOT = Path(os.environ.get("W24_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
VAULT_ROOT = LAB_ROOT / "vault"
DEFAULT_DATA_DIR = Path(os.environ.get("W24_DATA_DIR", LAB_ROOT / "data"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Week 24 offline HomeLab SRE agent simulator")
    commands = root.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="Run one deterministic incident and pause for human approval")
    demo.add_argument("--case", choices=fixture_ids(), default="proxy-rule-mismatch")
    demo.add_argument("--request", help="Incident description; only the Netflix fixture is supported")
    demo.add_argument("--decision", choices=("approve", "reject"), help="Explicit runtime approval/rejection")
    demo.add_argument("--approver", default="local-human")
    demo.add_argument("--thread-id")
    demo.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    demo.add_argument("--save-report", action="store_true", help="Offer a separate confirmed knowledge export")

    resume = commands.add_parser("resume", help="Resume a checkpointed approval interrupt")
    resume.add_argument("thread_id")
    resume.add_argument("--decision", choices=("approve", "reject"), required=True)
    resume.add_argument("--approver", required=True)
    resume.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    evaluate = commands.add_parser("eval", help="Run all deterministic golden cases")
    evaluate.add_argument("--output-dir", type=Path, default=DEFAULT_DATA_DIR / "evals")

    metrics = commands.add_parser("metrics", help="Print counters from locally recorded demo runs")
    metrics.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return root


def _interactive_approval(payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    print("\nHuman approval required before the simulated write tool can be started.")
    print(f"Cause: {payload['cause']}")
    print(f"Proposal: {payload['description']}")
    print(f"Expected effect: {payload['expected_effect']}")
    if args.decision:
        print(f"Explicit CLI decision: {args.decision} (approver={args.approver})")
        return approval_reply(payload, args.decision, args.approver)
    try:
        choice = input("Type approve or reject (anything else leaves this run paused): ").strip().casefold()
    except EOFError:
        return None
    if choice not in {"approve", "reject"}:
        return None
    try:
        approver = input("Approver label: ").strip()
    except EOFError:
        return None
    if not approver:
        return None
    return approval_reply(payload, choice, approver)


def _print_run(run) -> int:
    if run.pending_approval:
        print("Approval is pending. No write tool was called.")
        print(f"Resume with: w24-sre resume {run.thread_id} --decision approve --approver <name>")
        return 0
    state = run.state
    print(state.get("report", "Workflow ended without a report."))
    print(f"\nthread_id={run.thread_id}")
    print(f"recovered={state.get('recovered', False)}")
    return 0 if state.get("report") else 1


def _confirm_report_export(report: str, run_id: str) -> None:
    destination = VAULT_ROOT / "knowledge" / "reports" / f"troubleshooting-{run_id}.md"
    print(f"\nSave this report as a new local knowledge note at {destination}?")
    try:
        answer = input("Type SAVE to confirm this file write: ").strip()
    except EOFError:
        return
    if answer == "SAVE":
        print(f"Saved: {save_report_to_knowledge(report, run_id, VAULT_ROOT)}")
    else:
        print("Report was not saved to the knowledge vault.")


def _print_metrics(data_dir: Path) -> int:
    metrics_dir = data_dir / "metrics"
    files = sorted(metrics_dir.glob("*.json")) if metrics_dir.exists() else []
    if not files:
        print("No metrics recorded yet.")
        return 0
    recorder = TraceRecorder("metrics")
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        recorder.counters.update(data.get("counters", {}))
        for key, value in data.get("duration_ms", {}).items():
            recorder.duration_ms[key] += float(value)
    print(recorder.prometheus_text(), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "demo":
        scenario = get_scenario(args.case)
        thread_id = args.thread_id or new_thread_id()
        try:
            run = asyncio.run(run_new_workflow(
                request=args.request or scenario.request,
                case_id=scenario.case_id,
                thread_id=thread_id,
                vault_root=VAULT_ROOT,
                checkpoint_path=args.data_dir / "checkpoints.sqlite",
                telemetry_dir=args.data_dir,
                approval_provider=lambda payload: _interactive_approval(payload, args),
            ))
        except (ValueError, RuntimeError) as exc:
            print(f"Demo failed: {exc}", file=sys.stderr)
            return 1
        result = _print_run(run)
        if args.save_report and run.state.get("report"):
            _confirm_report_export(run.state["report"], thread_id)
        return result
    if args.command == "resume":
        try:
            run = asyncio.run(resume_workflow(
                thread_id=args.thread_id,
                decision=args.decision,
                approver=args.approver,
                vault_root=VAULT_ROOT,
                checkpoint_path=args.data_dir / "checkpoints.sqlite",
                telemetry_dir=args.data_dir,
            ))
        except (ValueError, RuntimeError) as exc:
            print(f"Resume failed: {exc}", file=sys.stderr)
            return 1
        return _print_run(run)
    if args.command == "eval":
        summary = asyncio.run(run_evals(
            dataset_path=LAB_ROOT / "evals" / "golden.jsonl",
            vault_root=VAULT_ROOT,
            output_dir=args.output_dir,
        ))
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["passed"] else 1
    if args.command == "metrics":
        return _print_metrics(args.data_dir)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
