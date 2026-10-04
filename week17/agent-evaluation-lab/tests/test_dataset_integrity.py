"""Dataset structural + sanitizer validation (negative mutations must be rejected)."""

from collections import Counter

import pytest
from pydantic import ValidationError

from week17_agent_evaluation_lab.dataset import (
    load_dataset,
    load_raw_records,
    parse_record,
    validate_dataset,
)


def test_valid_dataset_counts_and_ids(records):
    assert validate_dataset(records) == []
    assert len(records) == 30
    assert Counter(r.category for r in records) == {"network": 10, "docker": 10, "esxi": 10}
    assert len({r.case_id for r in records}) == 30
    assert all(r.case_id.split("-")[1] in {"NET", "DOC", "ESX"} for r in records)


def test_duplicate_id_rejected(records):
    recs = list(records)
    recs[1].case_id = recs[0].case_id
    assert any("duplicate" in e.lower() for e in validate_dataset(recs))


def test_wrong_total_count_rejected(records):
    assert validate_dataset(records[:-1])


def test_unknown_category_rejected(records):
    recs = list(records)
    recs[0].category = "storage"
    assert validate_dataset(recs)


def test_prefix_category_mismatch_rejected(records):
    recs = list(records)
    recs[0].case_id = "W17-DOC-001"
    assert validate_dataset(recs)


def test_oversized_question_rejected(records):
    recs = list(records)
    recs[0].question = "x" * 2001
    assert validate_dataset(recs)


def test_non_contract_tool_sequence_rejected(records):
    recs = list(records)
    recs[0].expected.mcp_contract.tool_sequence = ["get_health_status", "ping"]
    assert validate_dataset(recs)


def test_empty_rag_rows_rejected(records):
    recs = list(records)
    recs[0].fixture.rag_rows = []
    assert validate_dataset(recs)


def test_non_fixture_source_path_rejected(records):
    recs = list(records)
    recs[0].fixture.rag_rows[0].source_path = "/Users/operator/private-notes.md"
    assert validate_dataset(recs)


def test_credential_looking_content_rejected(records):
    recs = list(records)
    recs[0].fixture.rag_rows[0].content = "set api_key: sk-do-not-store-this"
    assert validate_dataset(recs)


def test_extra_field_rejected_at_parse():
    raw = load_raw_records("data/golden_eval.jsonl")[0]
    with pytest.raises(ValidationError):
        parse_record({**raw, "unexpected_field": 1})


def test_caps_match_agent_limits(records):
    rec = records[0]
    assert 1 <= len(rec.question) <= 2000
    for row in rec.fixture.rag_rows:
        assert len(row.content) <= 2000
        assert len(row.source_path) <= 1000
        assert len(row.heading_path) <= 500
