import json
import shutil
from pathlib import Path

from autonomous_homelab_sre_agent import workflow
from autonomous_homelab_sre_agent.evals import run_evals
from autonomous_homelab_sre_agent.knowledge import ObsidianRetriever
from autonomous_homelab_sre_agent.report import save_report_to_knowledge
from autonomous_homelab_sre_agent.scenarios import get_scenario


LAB_ROOT = Path(__file__).parents[1]


async def test_three_complete_golden_demos_are_repeatable(tmp_path):
    first = await run_evals(
        dataset_path=LAB_ROOT / "evals" / "golden.jsonl",
        vault_root=LAB_ROOT / "vault",
        output_dir=tmp_path / "first",
    )
    second = await run_evals(
        dataset_path=LAB_ROOT / "evals" / "golden.jsonl",
        vault_root=LAB_ROOT / "vault",
        output_dir=tmp_path / "second",
    )

    assert first["passed"] is True
    assert first["case_count"] == first["passed_cases"] == 3
    assert first == second
    assert first["approval_gate"]["passed"] is True
    assert first["approval_gate"]["pause"]["checks"]["no_write_tool_call"] is True
    assert first["approval_gate"]["reject"]["checks"]["no_write_tool_call"] is True
    for case in first["cases"]:
        assert case["checks"]["ten_read_calls"] is True
        assert case["checks"]["one_simulated_write"] is True
        assert case["checks"]["approval_interrupt_observed"] is True
        report = (tmp_path / "first" / case["report"]).read_text()
        assert case["citations"]
        assert "All required checks recovered: **True**." in report
        trace = (tmp_path / "first" / case["trace"]).read_text()
        assert "approval_capability" not in trace

    saved = json.loads((tmp_path / "first" / "eval-results.json").read_text())
    assert saved == first


async def test_eval_fails_if_interrupt_is_replaced_with_automatic_approval(monkeypatch, tmp_path):
    def automatic_approval(payload):
        return {
            "decision": "approve",
            "action_id": payload["action_id"],
            "proposal_digest": payload["proposal_digest"],
            "approver": "automatic-mutation",
        }

    async def simulated_only_write(case_id, *, action_id, digest, on_tool=None):
        if on_tool:
            on_tool("apply_simulated_remediation", "started")
            on_tool("apply_simulated_remediation", "ok")
        return {
            "status": "simulated",
            "action_id": action_id,
            "overlay": action_id,
            "audit_id": f"mutation-test-{case_id}",
        }

    monkeypatch.setattr(workflow, "interrupt", automatic_approval)
    monkeypatch.setattr(workflow, "apply_simulated_remediation", simulated_only_write)
    result = await run_evals(
        dataset_path=LAB_ROOT / "evals" / "golden.jsonl",
        vault_root=LAB_ROOT / "vault",
        output_dir=tmp_path / "automatic-approval-mutation",
    )

    assert result["passed"] is False
    assert all(not case["checks"]["approval_interrupt_observed"] for case in result["cases"])
    assert result["approval_gate"]["passed"] is False
    assert result["approval_gate"]["pause"]["passed"] is False
    assert result["approval_gate"]["reject"]["passed"] is False


async def test_saved_proxy_report_is_secondary_context_and_eval_recovers(tmp_path):
    vault_root = tmp_path / "vault"
    shutil.copytree(LAB_ROOT / "vault", vault_root)
    report = (LAB_ROOT / "evidence" / "eval-run" / "reports" / "proxy-rule-mismatch.md").read_text()
    saved_path = save_report_to_knowledge(report, "review_export", vault_root)
    assert saved_path == vault_root / "knowledge" / "reports" / "troubleshooting-review_export.md"
    save_report_to_knowledge(report, "prior_proxy_run", vault_root)

    scenario = get_scenario("proxy-rule-mismatch")
    retrieved = ObsidianRetriever(vault_root).retrieve(
        scenario.request,
        topic_terms=scenario.topic_terms,
    )
    sources = {item.source for item in retrieved.citations}
    assert "knowledge/netflix-routing.md" in sources
    assert any("should use the `PROXY` action" in item.excerpt for item in retrieved.citations)
    report_citations = [
        item for item in retrieved.citations
        if item.source.startswith("knowledge/reports/")
    ]
    assert len(report_citations) == 1
    assert retrieved.citations.index(report_citations[0]) > max(
        index for index, item in enumerate(retrieved.citations)
        if item.source == "knowledge/netflix-routing.md"
    )

    result = await run_evals(
        dataset_path=LAB_ROOT / "evals" / "golden.jsonl",
        vault_root=vault_root,
        output_dir=tmp_path / "with-saved-report",
    )
    assert result["passed"] is True
    proxy_case = next(case for case in result["cases"] if case["case_id"] == "proxy-rule-mismatch")
    assert proxy_case["cause"] == "route_mismatch"
    assert proxy_case["checks"]["cited_required_source"] is True
