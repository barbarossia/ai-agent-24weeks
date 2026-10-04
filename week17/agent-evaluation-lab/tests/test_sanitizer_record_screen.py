"""H006-B1: record-level sanitizer screen must cover the record's own text fields.

Synthetic strings only; no real-looking data is added to the shipped dataset.
"""

from week17_agent_evaluation_lab.dataset import validate_dataset


def _with(records, **overrides):
    rec = records[0].model_copy(deep=True)
    for key, value in overrides.items():
        if key.startswith("rag_"):
            row = rec.fixture.rag_rows[0].model_copy(deep=True)
            setattr(row, key.removeprefix("rag_"), value)
            rec.fixture.rag_rows[0] = row
        else:
            setattr(rec, key, value)
    return [rec, *records[1:]]


def _rejected(records) -> bool:
    return len(validate_dataset(records)) > 0


def test_question_with_email_rejected(records):
    assert _rejected(_with(records, question="为什么 admin@example.invalid 收不到告警？"))


def test_question_with_home_path_rejected(records):
    assert _rejected(_with(records, question="路径 /Users/synthetic-user/notes 为何抓不到日志？"))


def test_question_with_credential_token_rejected(records):
    assert _rejected(_with(records, question="用 token=0123456789abcdef 重新登录后仍失败？"))


def test_notes_with_email_rejected(records):
    assert _rejected(_with(records, notes="contact ops-team@example.invalid"))


def test_tags_with_internal_ip_rejected(records):
    assert _rejected(_with(records, tags=["prod", "10.20.30.40"]))


def test_question_with_internal_ip_rejected(records):
    assert _rejected(_with(records, question="生产网段 10.20.30.40 为何不可达？"))


def test_notes_with_internal_ip_rejected(records):
    assert _rejected(_with(records, notes="observed on 192.168.50.10 during the drill"))


def test_shipped_dataset_still_clean(records):
    assert validate_dataset(records) == []
