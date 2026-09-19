"""CLI 测试：每个演示命令都可运行，且输出可断言（含退出码）。"""

from __future__ import annotations

import json

import pytest

from llm_api_lab.cli import main


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_demo_runs_structured_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "raw (model) :" in out
    assert "validated   :" in out
    assert "repairs     : 0" in out


def test_demo_accepts_custom_question(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", "--question", "DNS 解析失败导致宕机"]) == 0
    out = capsys.readouterr().out
    assert '"category":"network"' in out


def test_invalid_json_scenario_repairs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["invalid-json"]) == 0
    out = capsys.readouterr().out
    assert "repairs     : 1" in out
    assert "provider 调用次数: 2" in out


def test_retry_scenario_shows_attempts_and_delays(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["retry"]) == 0
    out = capsys.readouterr().out
    assert "attempts    : 3" in out
    assert "[0.2, 0.2]" in out


def test_stream_scenario_assembles(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stream"]) == 0
    out = capsys.readouterr().out
    assert "assembled  :" in out
    assert '"category"' in out


def test_schema_command_prints_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "properties" in payload
    assert "severity" in payload["properties"]


def test_budget_scenario_blocks(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["budget"]) == 0
    out = capsys.readouterr().out
    assert "blocked before sending" in out


def test_unknown_command_exits_with_code_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["nope"])
    assert excinfo.value.code == 2
