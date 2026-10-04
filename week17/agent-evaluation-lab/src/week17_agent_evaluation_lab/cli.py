"""CLI for the Week 17 lab. Exit codes: 0 ok, 2 validation/violation, 1 redacted unexpected."""

from __future__ import annotations

import argparse
import sys

from .constants import JUDGE_PROVENANCE_SHORT
from .dataset import dataset_summary, load_dataset, validate_dataset
from .judge import prepare_packet, record_verdict
from .runner import run_dataset, write_artifacts


def parser():
    root = argparse.ArgumentParser(prog="week17-eval", description="Week 17 deterministic offline agent evaluation")
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="Validate the golden dataset")
    validate.add_argument("--dataset", required=True)

    run = commands.add_parser("run", help="Run the deterministic offline evaluation")
    run.add_argument("--dataset", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--fail-on-violation", action="store_true")

    judge = commands.add_parser("judge", help="Manual Judge packet/record (no model call)")
    judge.add_argument("--dataset", required=True)
    judge.add_argument("--case")
    mode = judge.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--record", metavar="VERDICT_JSON")
    judge.add_argument("--out", default="judge/packets")

    return root


def _cmd_validate(args) -> int:
    records = load_dataset(args.dataset)
    errors = validate_dataset(records)
    if errors:
        for error in errors:
            print(f"invalid: {error}", file=sys.stderr)
        return 2
    print(dataset_summary(records))
    return 0


def _cmd_run(args) -> int:
    records = load_dataset(args.dataset)
    errors = validate_dataset(records)
    if errors:
        for error in errors:
            print(f"invalid: {error}", file=sys.stderr)
        return 2
    run = run_dataset(records)
    out = write_artifacts(run, args.out)
    agg = run.report["aggregates"]
    print(
        f"evaluated {agg['total']} cases: passed={agg['passed']} "
        f"failed={agg['failed']} blocked={agg['blocked']} "
        f"contract_violations={agg['contract_violations']}"
    )
    print(f"artifacts written to {out.name}/ (report.json, trajectory.jsonl, run_meta.json)")
    if args.fail_on_violation and agg["contract_violations"] > 0:
        return 2
    return 0


def _cmd_judge(args) -> int:
    records = load_dataset(args.dataset)
    if args.prepare:
        if not args.case:
            print("--case is required with --prepare", file=sys.stderr)
            return 2
        record = next((r for r in records if r.case_id == args.case), None)
        if record is None:
            print(f"unknown case: {args.case}", file=sys.stderr)
            return 2
        path = prepare_packet(record, args.out)
        print(f"wrote redacted judge packet: {path.name}")
        print(JUDGE_PROVENANCE_SHORT)
        return 0

    errors = record_verdict(args.record, records)
    if errors:
        for error in errors:
            print(f"invalid verdict: {error}", file=sys.stderr)
        return 2
    print("verdict schema valid; Judge path is separate from the deterministic offline score.")
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "judge":
            return _cmd_judge(args)
        return 1
    except Exception:
        print("Operation failed; verify input and local dependencies.", file=sys.stderr)
        return 1
