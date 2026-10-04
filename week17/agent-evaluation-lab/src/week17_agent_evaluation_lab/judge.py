"""Manual LLM-as-Judge seam (offline prepare/record only; no model is called).

The packet is redacted: it contains the question, the fixture knowledge rows, the
deterministic canned answer and contract evidence — never tokens, raw JSON-RPC,
environment values, or absolute paths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .runner import run_case

VERDICTS = ("good", "weak", "bad")
VERDICT_SOURCES = ("user-supplied-example", "human-observed")

_REDACTIONS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"(?:/Users/|/home/)[^\s)]+"),
)


def redact(text: str) -> str:
    for pattern in _REDACTIONS:
        text = pattern.sub("[redacted]", text)
    return text


def build_packet(record) -> str:
    case = run_case(record)
    lines = [
        f"# Judge packet — {record.case_id}",
        "",
        "This packet is an offline, redacted artifact. No model was called to produce it.",
        "",
        "## Question",
        record.question,
        "",
        "## Fixture knowledge rows (as shown to generation)",
    ]
    for row in record.fixture.rag_rows:
        lines += [
            f"### {row.source_path} — {row.heading_path}",
            row.content,
            f"similarity: {row.similarity}",
            "",
        ]
    lines += [
        "## Deterministic canned answer",
        case["final_answer"],
        "",
        "## Contract evidence",
        f"- mcp_tool_sequence: {case['mcp_tool_sequence']}",
        f"- checks: {json.dumps(case['checks'], sort_keys=True)}",
        f"- status: {case['status']} (failed_stage: {case['failed_stage']})",
        "",
        "The judge may optionally reuse this packet outside CI. The deterministic",
        "offline score does not depend on any judge verdict.",
    ]
    return redact("\n".join(lines)) + "\n"


def prepare_packet(record, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{record.case_id}.md"
    path.write_text(build_packet(record), encoding="utf-8")
    return path


def _known_case_ids(records) -> set[str]:
    return {record.case_id for record in records}


def validate_verdict(verdict: dict, records) -> list[str]:
    errors: list[str] = []
    case_id = verdict.get("case_id")
    if not isinstance(case_id, str) or case_id not in _known_case_ids(records):
        errors.append(f"unknown case_id: {case_id!r}")
    if verdict.get("judge_verdict") not in VERDICTS:
        errors.append(f"judge_verdict must be one of {VERDICTS}")
    if verdict.get("verdict_source") not in VERDICT_SOURCES:
        errors.append(f"verdict_source must be one of {VERDICT_SOURCES}")
    if not isinstance(verdict.get("reasons"), str) or not verdict["reasons"].strip():
        errors.append("reasons must be a non-empty string")
    if not isinstance(verdict.get("reviewed_at"), str) or not verdict["reviewed_at"].strip():
        errors.append("reviewed_at must be a non-empty string")
    if not isinstance(verdict.get("reviewer_initials"), str) or not verdict["reviewer_initials"].strip():
        errors.append("reviewer_initials must be a non-empty string")
    return errors


def record_verdict(path: str | Path, records) -> list[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_verdict(raw, records)
