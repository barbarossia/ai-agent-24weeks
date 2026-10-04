"""Two consecutive full runs must produce byte-identical compared artifacts."""

import json

from week17_agent_evaluation_lab.runner import run_dataset, write_artifacts


def test_compared_artifacts_are_byte_identical_across_runs(records, tmp_path):
    first = run_dataset(records)
    write_artifacts(first, tmp_path / "run1")
    second = run_dataset(records)
    write_artifacts(second, tmp_path / "run2")

    for name in ("report.json", "trajectory.jsonl"):
        a = (tmp_path / "run1" / name).read_bytes()
        b = (tmp_path / "run2" / name).read_bytes()
        assert a == b, f"{name} differed between runs"

    # Volatile data is isolated to run_meta.json only.
    report_text = (tmp_path / "run1" / "report.json").read_text()
    traj_text = (tmp_path / "run1" / "trajectory.jsonl").read_text()
    assert "started_at" not in report_text and "duration_ms" not in report_text
    assert "started_at" not in traj_text and "duration_ms" not in traj_text
    meta = json.loads((tmp_path / "run1" / "run_meta.json").read_text())
    assert "started_at" in meta and "duration_ms" in meta

    # Frozen clock is recorded as a constant.
    report = json.loads(report_text)
    assert report["clock_frozen_to"] == "2026-01-01T00:00:00+00:00"


def test_report_json_is_sorted_and_has_no_absolute_home_paths(records, tmp_path):
    run = run_dataset(records)
    write_artifacts(run, tmp_path / "out")
    text = (tmp_path / "out" / "report.json").read_text()
    assert "/Users/" not in text and "/home/" not in text
    # sort_keys=True: the first metadata key is alphabetically first.
    report = json.loads(text)
    assert list(report.keys()) == sorted(report.keys())
