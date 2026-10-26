from pathlib import Path

import pytest

from autonomous_homelab_sre_agent.report import save_report_to_knowledge
from autonomous_homelab_sre_agent.telemetry import TraceRecorder


def test_trace_links_tool_span_to_node_and_exports_metrics(tmp_path):
    recorder = TraceRecorder("trace-review")
    with recorder.span("diagnostics.read_only", case_id="proxy-rule-mismatch"):
        recorder.tool_event("dns_lookup", "started")
        recorder.tool_event("dns_lookup", "ok")
    recorder.increment("workflow_runs_total", outcome="recovered")

    trace_path, metrics_path = recorder.write(tmp_path)
    span_text = trace_path.read_text()
    assert '"parent_span_id": "trace-review-0001"' in span_text
    metrics = recorder.prometheus_text()
    assert 'w24_mcp_tool_calls_total{tool="dns_lookup",outcome="ok"} 1' in metrics
    assert 'w24_workflow_runs_total{outcome="recovered"} 1' in metrics
    assert metrics_path.exists()


def test_knowledge_report_export_is_fixed_to_vault_and_rejects_path_injection(tmp_path):
    vault = tmp_path / "vault"
    path = save_report_to_knowledge("# Report\n", "run_123", vault)
    assert path == vault / "reports" / "troubleshooting-run_123.md"
    assert path.read_text() == "# Report\n"
    with pytest.raises(ValueError, match="invalid run identifier"):
        save_report_to_knowledge("# Report\n", "../../outside", vault)


def test_knowledge_report_export_rejects_symlink_target(tmp_path):
    vault = tmp_path / "vault"
    reports = vault / "reports"
    reports.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("leave alone")
    (reports / "troubleshooting-run_123.md").symlink_to(outside)

    with pytest.raises(ValueError, match="regular file"):
        save_report_to_knowledge("# Report\n", "run_123", vault)
    assert outside.read_text() == "leave alone"
