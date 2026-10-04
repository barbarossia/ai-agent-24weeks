"""Per-case evaluation runner.

Each case runs the **real** ``KnowledgeAgent`` with a real ``MockHomeLab``:
RAG and generation are scripted doubles, and the MCP transport plus the clock
are runtime-patched. Stages are recorded without wall-clock data so the compared
artifacts (``report.json`` + ``trajectory.jsonl``) are byte-stable.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from homelab_knowledge_agent.agent import KnowledgeAgent
from homelab_knowledge_agent.errors import IntegrationBlocked

from .clock import CLOCK_FROZEN_TO
from .constants import DISCLAIMER
from .doubles import (
    DEFAULT_HEALTH,
    RecordingSession,
    ScriptedGeneration,
    ScriptedRag,
    patch_homelab_transport,
)
from .clock import freeze_homelab_clock

STAGE_ORDER = ("retrieval", "mcp", "generation", "answer_checks")


def _digest(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stage(stage: str, status: str, in_digest: str, out_digest: str, detail: str) -> dict:
    return {
        "stage": stage,
        "status": status,
        "inputs_digest": in_digest,
        "outputs_digest": out_digest,
        "detail": detail[:500],
    }


def _health_payload(record):
    if record.fixture.mcp_health_data == "default-mock":
        return None  # RecordingSession uses DEFAULT_HEALTH
    return json.loads(record.fixture.mcp_health_data)


class _RealHomelab:
    """The real Week 12 MockHomeLab (transport is patched by the runner)."""

    def __init__(self):
        from homelab_knowledge_agent.homelab import MockHomeLab

        self._inner = MockHomeLab()

    async def collect(self):
        return await self._inner.collect()


def _evaluate_answer(record, answer: str) -> tuple[bool, str]:
    answer_lower = answer.lower()
    if not any(token.lower() in answer_lower for token in record.expected.answer.must_include_any):
        return False, "answer missing all must_include_any tokens"
    for token in record.expected.answer.must_not_include:
        if token.lower() in answer_lower:
            return False, f"answer contains forbidden token {token!r}"
    if record.expected.answer.provenance:
        if "Knowledge sources:" not in answer or "MCP live data: MockAdapter" not in answer:
            return False, "answer missing required provenance/disclosure block"
    return True, "answer contract checks passed"


def run_case(record, *, session=None, generation=None) -> dict:
    session = session if session is not None else RecordingSession(health_payload=_health_payload(record))
    generation = generation if generation is not None else ScriptedGeneration(record)
    rag = ScriptedRag(record)

    stages: list[dict] = []
    checks = {"retrieval": False, "mcp": False, "generation": False, "answer_checks": False}
    failed_stage = None
    final_answer = ""
    knowledge_count = 0
    prompt = ""
    known_call = [("ping", {}), ("get_health_status", {})]

    # --- retrieval stage -------------------------------------------------
    try:
        rows = rag.retrieve(record.question)
        knowledge_count = min(len(rows), 5)
        payload_paths = [r["source_path"] for r in rows[:5]]
        ok = (
            len(rag.calls) == 1
            and rag.calls[0] == record.question
            and knowledge_count >= record.expected.retrieval.min_rows
            and record.expected.retrieval.required_source_path in payload_paths
        )
        checks["retrieval"] = ok
        stages.append(
            _stage(
                "retrieval",
                "pass" if ok else "fail",
                _digest(record.question),
                _digest(payload_paths),
                f"retrieved {knowledge_count} rows; required={record.expected.retrieval.required_source_path}",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        stages.append(_stage("retrieval", "fail", _digest(record.question), _digest("error"), str(exc)))
    if not checks["retrieval"]:
        return _finalize(record, stages, checks, "retrieval", final_answer, knowledge_count, prompt, session)

    # --- mcp contract stage (single real agent invocation) --------------
    agent = KnowledgeAgent(rag, _RealHomelab(), generation)
    contract = record.expected.mcp_contract
    recorded: list[tuple[str, dict]] = []
    live_ok = False
    answer = None
    caught: Exception | None = None
    try:
        with patch_homelab_transport(session), freeze_homelab_clock():
            import asyncio

            answer = asyncio.run(agent.answer(record.question))
    except Exception as exc:
        caught = exc
    finally:
        recorded = [(name, args) for name, args in session.calls]

    mcp_ok = (
        recorded == known_call
        and all(args == {} for _, args in recorded)
        and contract.tool_sequence == [name for name, _ in recorded]
        and contract.all_arguments_empty is True
    )
    checks["mcp"] = mcp_ok
    stages.append(
        _stage(
            "mcp",
            "pass" if mcp_ok else "fail",
            _digest(record.question),
            _digest(recorded),
            f"recorded tool calls={recorded}",
        )
    )
    if not mcp_ok:
        return _finalize(record, stages, checks, "mcp", final_answer, knowledge_count, prompt, session)

    if caught is not None:
        stage = "generation" if generation.calls else "mcp"
        stages.append(_stage(stage, "blocked", _digest(record.question), _digest("blocked"), str(caught)[:300]))
        return _finalize(record, stages, checks, stage, final_answer, knowledge_count, prompt, session)

    checks["generation"] = bool(generation.calls)
    prompt = generation.calls[0] if generation.calls else ""
    stages.append(
        _stage(
            "generation",
            "pass" if checks["generation"] else "fail",
            _digest(record.question),
            _digest(prompt),
            "generation seam received the prompt",
        )
    )
    if not checks["generation"]:
        return _finalize(record, stages, checks, "generation", final_answer, knowledge_count, prompt, session)

    final_answer = answer
    answer_ok, detail = _evaluate_answer(record, answer)
    checks["answer_checks"] = answer_ok
    stages.append(
        _stage(
            "answer_checks",
            "pass" if answer_ok else "fail",
            _digest(prompt),
            _digest(answer),
            detail,
        )
    )
    if not answer_ok:
        failed_stage = "answer_checks"

    return _finalize(record, stages, checks, failed_stage, final_answer, knowledge_count, prompt, session)


def _finalize(record, stages, checks, failed_stage, final_answer, knowledge_count, prompt, session) -> dict:
    status = "pass" if all(checks.values()) else ("blocked" if failed_stage in {"mcp", "generation"} and not all(checks.values()) else "fail")
    if all(checks.values()):
        status = "pass"
    return {
        "case_id": record.case_id,
        "category": record.category,
        "status": status,
        "failed_stage": failed_stage,
        "stages": stages,
        "checks": checks,
        "knowledge_count": knowledge_count,
        "mcp_tool_sequence": [name for name, _ in session.calls],
        "answer_digest": _digest(final_answer),
        "final_answer": final_answer,
    }


@dataclass
class DatasetRun:
    report: dict
    trajectory: list[dict]
    meta: dict = field(default_factory=dict)
    cases: list[dict] = field(default_factory=list)


def _aggregate(cases: list[dict]) -> dict:
    by_category: dict[str, dict] = {}
    for category in ("network", "docker", "esxi"):
        subset = [c for c in cases if c["category"] == category]
        by_category[category] = {
            "total": len(subset),
            "passed": sum(1 for c in subset if c["status"] == "pass"),
            "failed": sum(1 for c in subset if c["status"] != "pass"),
        }
    per_check_failures = {
        check: sum(1 for c in cases if not c["checks"][check]) for check in STAGE_ORDER
    }
    first_failing_stage_counts: dict[str, int] = {}
    for case in cases:
        if case["failed_stage"]:
            first_failing_stage_counts[case["failed_stage"]] = (
                first_failing_stage_counts.get(case["failed_stage"], 0) + 1
            )
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "pass")
    provenance_complete = sum(
        1 for c in cases if c["checks"]["answer_checks"] and c["status"] == "pass"
    )
    return {
        "total": total,
        "passed": passed,
        "failed": sum(1 for c in cases if c["status"] == "fail"),
        "blocked": sum(1 for c in cases if c["status"] == "blocked"),
        "contract_violations": sum(1 for c in cases if not c["checks"]["mcp"]),
        "provenance_completeness": round(provenance_complete / total, 4) if total else 0.0,
        "per_check_failures": per_check_failures,
        "first_failing_stage_counts": first_failing_stage_counts,
        "by_category": by_category,
    }


def run_dataset(records) -> DatasetRun:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    cases = [run_case(record) for record in records]
    finished_at = datetime.now(timezone.utc).isoformat()
    duration_ms = round((time.perf_counter() - started) * 1000, 3)

    report = {
        "schema_version": "1",
        "clock_frozen_to": CLOCK_FROZEN_TO.isoformat(),
        "disclaimer": DISCLAIMER,
        "judge_provenance": (
            "示例判定为用户提供的样例（仅验证 Judge schema 与流程），本轮未调用任何模型；"
            "Judge 路径与确定性离线评测分离，离线指标不依赖 Judge。"
        ),
        "aggregates": _aggregate(cases),
        "cases": [
            {
                "case_id": c["case_id"],
                "category": c["category"],
                "status": c["status"],
                "failed_stage": c["failed_stage"],
                "checks": c["checks"],
                "knowledge_count": c["knowledge_count"],
                "mcp_tool_sequence": c["mcp_tool_sequence"],
                "answer_digest": c["answer_digest"],
            }
            for c in cases
        ],
    }
    trajectory = [
        {
            "case_id": c["case_id"],
            "status": c["status"],
            "failed_stage": c["failed_stage"],
            "stages": c["stages"],
        }
        for c in cases
    ]
    meta = {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "case_count": len(cases),
    }
    return DatasetRun(report=report, trajectory=trajectory, meta=meta, cases=cases)


def _dump_json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_artifacts(run: DatasetRun, out_dir: str | Path) -> Path:
    """Write compared artifacts (report.json, trajectory.jsonl) + volatile run_meta.json.

    Compared artifacts never contain the absolute output path or any wall clock.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(_dump_json(run.report), encoding="utf-8")
    (out / "trajectory.jsonl").write_text(
        "".join(
            json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n" for entry in run.trajectory
        ),
        encoding="utf-8",
    )
    (out / "run_meta.json").write_text(_dump_json(run.meta), encoding="utf-8")
    return out
