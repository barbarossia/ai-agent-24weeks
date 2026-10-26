from __future__ import annotations

from pathlib import Path
from typing import Any


def render_report(state: dict[str, Any]) -> str:
    incident = state.get("incident", {})
    diagnosis = state.get("diagnosis", {})
    review = state.get("review", {})
    proposal = state.get("proposal")
    approval = state.get("approval")
    remediation = state.get("remediation")
    verification = state.get("verification", {})
    recovered = state.get("recovered")
    initial_logs = state.get("observations", {}).get("read_recent_logs", {}).get("events", [])
    untrusted_log_events = sum(
        isinstance(event, dict) and event.get("code") == "UNTRUSTED_NOTE"
        for event in initial_logs
    )
    status = "recovered" if recovered else (
        "not approved" if approval and approval.get("decision") == "reject" else "unresolved"
    )

    lines = [
        "# Troubleshooting report: Netflix cannot be reached",
        "",
        f"- Run: `{state.get('run_id', 'unknown')}`",
        f"- Incident: {incident.get('request_summary', 'Netflix connectivity incident')}",
        f"- Case: `{state.get('case_id', 'unknown')}`",
        f"- Outcome: **{status}**",
        f"- Instruction-like user text detected and ignored: `{bool(incident.get('instruction_like_input', False))}`",
        f"- Retrieved knowledge paragraphs redacted: `{state.get('retrieval_redactions', 0)}`",
        f"- Instruction-like log events ignored: `{untrusted_log_events}`",
        "",
        "## Diagnosis",
        "",
        diagnosis.get("summary", "The available evidence did not establish a supported cause."),
        f"- Cause code: `{diagnosis.get('cause_code', 'inconclusive')}`",
        f"- Confidence: `{diagnosis.get('confidence', 0.0):.2f}`",
        f"- Independent review: `{bool(review.get('accepted', False))}` — {review.get('rationale', 'not reviewed')}",
        "",
        "## Initial evidence",
        "",
    ]
    _append_evidence_table(lines, state.get("observations", {}))
    if proposal:
        lines.extend([
            "",
            "## Proposed fix",
            "",
            f"- Action: `{proposal['action_id']}` — {proposal['description']}",
            f"- Expected effect: {proposal['expected_effect']}",
            f"- Approval: `{approval.get('decision') if approval else 'pending'}`",
            f"- Simulation result: `{remediation.get('status') if remediation else 'not executed'}`",
        ])
    lines.extend(["", "## Knowledge citations", ""])
    citations = diagnosis.get("citations", [])
    if citations:
        for citation in citations:
            lines.append(
                f"- `[[{citation['source']}#{citation['heading']}]]` line {citation['line']}: {citation['excerpt']}"
            )
    else:
        lines.append("- No runbook citation was used.")
    if verification:
        lines.extend(["", "## Recovery verification", ""])
        _append_evidence_table(lines, verification)
        lines.append(f"All required checks recovered: **{bool(recovered)}**.")
    lines.extend([
        "",
        "## Scope note",
        "",
        "All observations and actions in this report are local fixtures. The simulated remediation changed only an in-memory overlay; no real service was contacted.",
        "",
    ])
    return "\n".join(lines)


def _append_evidence_table(lines: list[str], observations: dict[str, dict[str, Any]]) -> None:
    lines.extend(["| Check | Result | Evidence IDs |", "|---|---|---|"])
    for tool, data in observations.items():
        fields = [
            f"{key}={value}"
            for key, value in data.items()
            if key not in {"events", "evidence_id"}
        ]
        events = data.get("events", [])
        codes = [str(event["code"]) for event in events if isinstance(event, dict) and "code" in event]
        if codes:
            fields.append(f"event_codes={codes}")
        identifiers = [data.get("evidence_id", tool)]
        identifiers.extend(
            event["evidence_id"]
            for event in events
            if isinstance(event, dict) and isinstance(event.get("evidence_id"), str)
        )
        lines.append(f"| `{tool}` | {'; '.join(fields) or 'events inspected'} | `{', '.join(identifiers)}` |")


def save_report_to_knowledge(report: str, run_id: str, vault_root: Path) -> Path:
    """Write one generated report under the fixed reports folder, with no caller path input."""
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("invalid run identifier")
    root = vault_root.resolve()
    report_dir = (root / "reports").resolve()
    if not report_dir.is_relative_to(root):
        raise ValueError("report destination must remain inside the knowledge vault")
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / f"troubleshooting-{run_id}.md"
    if target.is_symlink() or not target.resolve().parent.is_relative_to(report_dir):
        raise ValueError("report destination must be a regular file inside the knowledge vault")
    target.write_text(report, encoding="utf-8")
    return target
