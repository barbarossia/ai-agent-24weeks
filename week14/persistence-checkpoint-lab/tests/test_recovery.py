from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
THREAD_ID = "week14-test-thread"


def run_cli(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "persistence_checkpoint_lab.cli", "--db", str(db_path), "--thread-id", THREAD_ID, *args],
        cwd=PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_crash_restart_preserves_completed_steps_and_idempotent_effect(tmp_path: Path) -> None:
    db_path = tmp_path / "thread.sqlite"

    crashed = run_cli(db_path, "start", "--crash-step3")
    assert crashed.returncode == 86
    assert "Step1 ✓" in crashed.stdout
    assert "Step2 ✓" in crashed.stdout
    assert "Step3 crash before graph update" in crashed.stdout

    inspected = run_cli(db_path, "inspect")
    assert inspected.returncode == 0
    persisted = json.loads(inspected.stdout)
    assert persisted["values"]["completed_steps"] == ["Step1", "Step2"]
    assert persisted["next"] == ["step3"]
    assert persisted["mock_side_effect_count"] == 1

    resumed = run_cli(db_path, "resume")
    assert resumed.returncode == 0, resumed.stderr
    assert "Resuming thread" in resumed.stdout
    assert "Step1 ✓" not in resumed.stdout
    assert "Step2 ✓" not in resumed.stdout
    assert "Step3 side effect: already recorded" in resumed.stdout
    assert "Step3 ✓" in resumed.stdout

    completed = run_cli(db_path, "inspect")
    assert completed.returncode == 0, completed.stderr
    final = json.loads(completed.stdout)
    assert final["values"]["completed_steps"] == ["Step1", "Step2", "Step3"]
    assert final["next"] == []
    assert final["mock_side_effect_count"] == 1

    second_resume = run_cli(db_path, "resume")
    assert second_resume.returncode == 0
    assert "Thread already complete" in second_resume.stdout
    assert "Step3 ✓" not in second_resume.stdout
    assert json.loads(second_resume.stdout.split("\n", 1)[1])["mock_side_effect_count"] == 1


def test_unknown_thread_cannot_be_inspected_or_resumed(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"

    inspected = run_cli(db_path, "inspect")
    assert inspected.returncode == 2
    assert "Unknown thread: " + THREAD_ID in inspected.stdout

    resumed = run_cli(db_path, "resume")
    assert resumed.returncode == 2
    assert "Unknown thread: " + THREAD_ID in resumed.stdout
