"""CLI 测试：直接调用 ``main(argv)`` 并断言退出码与输出。

这种测试方式（而不是 subprocess）更快、更稳定，因为不需要启动新进程。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_agent_lab import cli
from ai_agent_lab.models import CheckResult, HealthStatus, Host


def test_list_prints_hosts(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "esxi-01" in out
    assert "openwrt-01" in out


def test_list_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--json", "list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {item["name"] for item in payload} == {"esxi-01", "docker-01", "openwrt-01", "nas-01"}


def test_check_single_host_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--json", "check", "esxi-01"])
    payload = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    assert payload["summary"]["total"] == 1
    assert payload["results"][0]["host"]["name"] == "esxi-01"


def test_check_unknown_host_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check", "ghost-99"]) == 2
    err = capsys.readouterr().err
    assert "ghost-99" in err
    assert "not found" in err


def test_check_all_json_summary(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--json", "check-all"])
    payload = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    summary = payload["summary"]
    assert summary["total"] == 4
    assert summary["up"] + summary["degraded"] + summary["down"] + summary["unknown"] == 4


def test_check_all_returns_1_when_any_down(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host(name="esxi-01", kind="esxi", address="192.168.1.10")
    down = CheckResult(host=host, status=HealthStatus.DOWN, latency_ms=9999, message="unreachable")
    # monkeypatch 掉 cli 模块引用的 check_all，制造“一定 DOWN”的场景
    monkeypatch.setattr(cli, "check_all", lambda inventory: [down])

    assert cli.main(["check-all"]) == 1
    assert "ATTENTION" in capsys.readouterr().out


def test_invalid_inventory_returns_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    assert cli.main(["--inventory", str(bad), "list"]) == 2
    assert "error:" in capsys.readouterr().err


def test_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2  # argparse 的用法错误退出码
