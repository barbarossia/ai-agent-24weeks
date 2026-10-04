"""Manual Judge packet/record: schema, provenance, redaction, no model call."""

import json

from week17_agent_evaluation_lab import cli
from week17_agent_evaluation_lab.judge import validate_verdict


def _verdict(case_id, **overrides):
    base = {
        "case_id": case_id,
        "judge_verdict": "good",
        "reasons": "user-supplied example verdict",
        "reviewed_at": "2026-01-01",
        "reviewer_initials": "EX",
        "verdict_source": "user-supplied-example",
    }
    base.update(overrides)
    return base


def test_validate_verdict_requires_provenance_and_known_case(records):
    assert validate_verdict(_verdict(records[0].case_id), records) == []
    assert validate_verdict(_verdict(records[0].case_id, verdict_source="guessed"), records)
    missing = _verdict(records[0].case_id)
    del missing["verdict_source"]
    assert validate_verdict(missing, records)
    assert validate_verdict(_verdict("W17-NET-999"), records)


def test_prepare_packet_is_redacted_and_exit_0(tmp_path, dataset_path, records):
    rc = cli.main(
        ["judge", "--prepare", "--case", records[0].case_id, "--dataset", str(dataset_path), "--out", str(tmp_path)]
    )
    assert rc == 0
    packet = (tmp_path / f"{records[0].case_id}.md").read_text()
    assert records[0].question in packet
    lowered = packet.lower()
    for forbidden in ("api_key", "authorization", "bearer ", "openai_api", "password"):
        assert forbidden not in lowered


def test_record_example_verdict_exit_0(tmp_path, dataset_path, records):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(_verdict(records[0].case_id)))
    assert cli.main(["judge", "--record", str(path), "--dataset", str(dataset_path)]) == 0


def test_record_missing_provenance_exit_2(tmp_path, dataset_path, records):
    bad = _verdict(records[0].case_id)
    del bad["verdict_source"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    assert cli.main(["judge", "--record", str(path), "--dataset", str(dataset_path)]) == 2
