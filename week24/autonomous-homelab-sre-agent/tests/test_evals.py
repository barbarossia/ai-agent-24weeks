import json
from pathlib import Path

from autonomous_homelab_sre_agent import workflow
from autonomous_homelab_sre_agent.evals import run_evals


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
