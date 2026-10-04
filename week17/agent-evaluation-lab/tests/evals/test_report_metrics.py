"""Aggregate metrics over the full golden dataset."""

from collections import Counter

from week17_agent_evaluation_lab.runner import run_dataset


def test_aggregate_metrics_match_hand_computed_table(records):
    run = run_dataset(records)
    agg = run.report["aggregates"]

    assert agg["total"] == 30
    assert agg["passed"] == 30
    assert agg["failed"] == 0
    assert agg["blocked"] == 0
    assert agg["contract_violations"] == 0
    assert agg["provenance_completeness"] == 1.0
    assert agg["per_check_failures"] == {"retrieval": 0, "mcp": 0, "generation": 0, "answer_checks": 0}
    assert agg["by_category"] == {
        "network": {"total": 10, "passed": 10, "failed": 0},
        "docker": {"total": 10, "passed": 10, "failed": 0},
        "esxi": {"total": 10, "passed": 10, "failed": 0},
    }
    assert agg["first_failing_stage_counts"] == {}

    counts = Counter(r.category for r in records)
    assert counts == {"network": 10, "docker": 10, "esxi": 10}
    assert all(len(case["mcp_tool_sequence"]) == 2 for case in run.report["cases"])
