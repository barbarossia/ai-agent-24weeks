import json
from pathlib import Path

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
    for case in first["cases"]:
        assert case["checks"]["ten_read_calls"] is True
        assert case["checks"]["one_simulated_write"] is True
        report = (tmp_path / "first" / case["report"]).read_text()
        assert case["citations"]
        assert "All required checks recovered: **True**." in report
        trace = (tmp_path / "first" / case["trace"]).read_text()
        assert "approval_capability" not in trace

    saved = json.loads((tmp_path / "first" / "eval-results.json").read_text())
    assert saved == first
