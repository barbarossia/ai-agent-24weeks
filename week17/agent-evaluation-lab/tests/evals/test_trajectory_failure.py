"""Controlled failures must pinpoint the exact case/stage."""

from week17_agent_evaluation_lab.doubles import RecordingSession, ScriptedGeneration
from week17_agent_evaluation_lab.runner import run_case


def test_all_stages_pass_for_a_clean_case(records):
    result = run_case(records[0])
    assert result["status"] == "pass"
    assert result["failed_stage"] is None
    assert result["checks"] == {
        "retrieval": True,
        "mcp": True,
        "generation": True,
        "answer_checks": True,
    }
    assert [s["stage"] for s in result["stages"]] == ["retrieval", "mcp", "generation", "answer_checks"]
    assert all("duration_ms" not in s and "started_at" not in s for s in result["stages"])


def test_generation_failure_is_pinned_to_generation(records):
    rec = records[0]
    result = run_case(rec, generation=ScriptedGeneration(rec, fail=True))
    assert result["status"] == "blocked"
    assert result["failed_stage"] == "generation"
    assert result["checks"]["retrieval"] is True
    assert result["checks"]["mcp"] is True
    assert result["checks"]["generation"] is False
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["generation"]["status"] == "blocked"


def test_mcp_transport_failure_is_pinned_to_mcp(records):
    rec = records[0]
    result = run_case(rec, session=RecordingSession(ping_payload={"adapter_mode": "openwrt", "read_only": True}))
    assert result["failed_stage"] == "mcp"
    assert result["checks"]["retrieval"] is True
    assert result["checks"]["mcp"] is False
    assert result["checks"]["generation"] is False
