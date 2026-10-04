"""CLI surface: validate/run/judge and stable 0/2/1 exit codes with redaction."""

import json

from week17_agent_evaluation_lab import cli


def test_validate_ok_exit_0(dataset_path):
    assert cli.main(["validate", "--dataset", str(dataset_path)]) == 0


def test_validate_invalid_exit_2(tmp_path, dataset_path):
    bad = tmp_path / "bad.jsonl"
    raw = dataset_path.read_text().splitlines()
    bad.write_text("\n".join(raw[:-1]) + "\n")  # 29 records -> invalid
    assert cli.main(["validate", "--dataset", str(bad)]) == 2


def test_run_exit_0_and_artifacts(tmp_path, dataset_path):
    out = tmp_path / "results"
    assert cli.main(["run", "--dataset", str(dataset_path), "--out", str(out), "--fail-on-violation"]) == 0
    assert (out / "report.json").exists()
    assert (out / "trajectory.jsonl").exists()
    assert (out / "run_meta.json").exists()
    report = json.loads((out / "report.json").read_text())
    assert report["aggregates"]["total"] == 30


def test_run_violation_exit_2(monkeypatch, tmp_path, dataset_path):
    from week17_agent_evaluation_lab import cli as cli_module

    class FakeRun:
        report = {"aggregates": {"contract_violations": 1, "total": 1, "passed": 0, "failed": 1, "blocked": 0}}
        trajectory = []
        meta = {}
        cases = []

    monkeypatch.setattr(cli_module, "run_dataset", lambda *a, **k: FakeRun())
    assert cli_module.main(["run", "--dataset", str(dataset_path), "--out", str(tmp_path / "o"), "--fail-on-violation"]) == 2


def test_unexpected_error_exit_1_is_redacted(monkeypatch, capsys, dataset_path):
    from week17_agent_evaluation_lab import cli as cli_module

    def boom(*args, **kwargs):
        raise RuntimeError("secret raw exception detail")

    monkeypatch.setattr(cli_module, "run_dataset", boom)
    assert cli_module.main(["run", "--dataset", str(dataset_path), "--out", "/tmp/does-not-matter"]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.out and "secret" not in captured.err
