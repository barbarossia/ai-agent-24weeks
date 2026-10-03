from __future__ import annotations

import json
import os
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langsmith import tracing_context

from long_running_workflow_lab.workflow import (CHECKS, MockBackends, build_graph,
                                                checkpoint_connection, clear_cancel,
                                                request_cancel)

PROJECT_DIR = Path(__file__).resolve().parents[1]


def run_cli(db: Path, thread: str, *args: str, env_extra: dict[str, str] | None = None):
    env = os.environ.copy()
    env.update({
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join((str(PROJECT_DIR / "src"), str(PROJECT_DIR / "tests"))),
    })
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "long_running_workflow_lab.cli", "--db", str(db),
         "--thread-id", thread, *args],
        cwd=PROJECT_DIR, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=False,
    )


def inspect(db: Path, thread: str) -> dict:
    result = run_cli(db, thread, "inspect")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def record_check_call(counters: Path, name: str) -> None:
    """Persist an attempt independently of the worker process's memory."""
    with sqlite3.connect(counters, timeout=5.0) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS check_calls (name TEXT PRIMARY KEY, calls INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO check_calls(name, calls) VALUES (?, 1) "
            "ON CONFLICT(name) DO UPDATE SET calls = calls + 1", (name,)
        )
        connection.commit()


def check_call_counts(counters: Path) -> dict[str, int]:
    if not counters.exists():
        return {}
    with sqlite3.connect(counters, timeout=5.0) as connection:
        return dict(connection.execute("SELECT name, calls FROM check_calls"))


def persisted_check_writes(db: Path, thread: str) -> set[str]:
    with sqlite3.connect(db, timeout=5.0) as connection:
        return {
            channel.removesuffix("_result")
            for (channel,) in connection.execute(
                "SELECT DISTINCT channel FROM writes WHERE thread_id=?", (thread,)
            )
            if channel.endswith("_result") and channel[:-7] in CHECKS
        }


def instrumented_cli(db: Path, thread: str, counters: Path, command: str) -> subprocess.CompletedProcess:
    """Run the real CLI while persisting check invocations for retry assertions."""
    inputs = counters.with_suffix(".inputs.jsonl")
    script = r'''import json, os, sqlite3, sys
from contextlib import contextmanager
from pathlib import Path
from long_running_workflow_lab.workflow import MockBackends

db, thread, counters, inputs, command = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
original = MockBackends.check
def counted(self, name, host, attempt, faults):
    with sqlite3.connect(counters, timeout=5.0) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS check_calls (name TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.execute("INSERT INTO check_calls(name, calls) VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET calls = calls + 1", (name,))
        connection.commit()
    return original(self, name, host, attempt, faults)
MockBackends.check = counted
from long_running_workflow_lab import cli
original_open = cli._open_graph
@contextmanager
def capture_open(db_path, backends=None):
    with original_open(db_path, backends) as graph:
        original_invoke = graph.invoke
        def captured(input, *args, **kwargs):
            entry = {"kind": "none"} if input is None else {"kind": "input", "value": input}
            with inputs.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, sort_keys=True) + "\n")
            return original_invoke(input, *args, **kwargs)
        graph.invoke = captured
        yield graph
cli._open_graph = capture_open
sys.argv = ["long-running-workflow-lab", "--db", str(db), "--thread-id", thread, command]
raise SystemExit(cli.main())
'''
    env = os.environ.copy()
    env.update({
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join((str(PROJECT_DIR / "src"), str(PROJECT_DIR / "tests"))),
    })
    return subprocess.run(
        [sys.executable, "-c", script, str(db), thread, str(counters), str(inputs), command],
        cwd=PROJECT_DIR, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=False,
    )


@pytest.fixture(autouse=True)
def network_disabled(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("offline lab attempted a network connection")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


def invoke_graph(db: Path, thread: str, backend: MockBackends, initial: dict, **config):
    connection = checkpoint_connection(db)
    with closing(connection), tracing_context(enabled=False):
        graph = build_graph(db, SqliteSaver(connection), backend)
        return graph.invoke(initial, config={"configurable": {"thread_id": thread, **config}},
                            durability="sync")


def test_start_fans_out_all_checks_and_pauses_for_approval(tmp_path: Path) -> None:
    db = tmp_path / "workflow.sqlite"
    run_id = "parallel"
    started = run_cli(db, run_id, "start", "--host", "lab.example")
    assert started.returncode == 0, started.stderr
    state = inspect(db, run_id)
    assert state["next"] == ["await_approval"]
    assert list(state["checks"]) == list(CHECKS)
    assert [state["checks"][name]["status"] for name in
            ("dns", "service", "connectivity", "logs")] == ["ok"] * 4
    assert state["run_status"] == "awaiting_approval"


def test_reject_never_calls_mock_fix(tmp_path: Path) -> None:
    db = tmp_path / "workflow.sqlite"
    log = tmp_path / "fix-calls.jsonl"
    env = {"W16_FIX_CALL_LOG": str(log)}
    assert run_cli(db, "reject", "start", env_extra=env).returncode == 0
    rejected = run_cli(db, "reject", "reject", env_extra=env)
    assert rejected.returncode == 0, rejected.stderr
    outcome = inspect(db, "reject")
    assert outcome["values"]["execution_status"] == "rejected"
    assert not log.exists() or log.read_text().strip() == ""


def test_separate_process_start_inspect_approve_completes(tmp_path: Path) -> None:
    db = tmp_path / "approval.sqlite"
    thread = "approval"
    log = tmp_path / "fix-calls.jsonl"
    env = {"W16_FIX_CALL_LOG": str(log)}
    started = run_cli(db, thread, "start", "--host", "router.lan", env_extra=env)
    assert started.returncode == 0, started.stderr
    waiting = run_cli(db, thread, "inspect", env_extra=env)
    assert waiting.returncode == 0
    assert json.loads(waiting.stdout)["next"] == ["await_approval"]
    approved = run_cli(db, thread, "approve", env_extra=env)
    assert approved.returncode == 0, approved.stderr
    assert json.loads(approved.stdout)["execution_status"] == "executed"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_four_checks_are_true_parallel_and_join_once(tmp_path: Path) -> None:
    backend = MockBackends(entered=threading.Barrier(4))
    result = invoke_graph(tmp_path / "parallel.sqlite", "parallel", backend,
                          {"host": "host", "retry_nonce": 0})
    evidence = backend.snapshot()
    assert result.get("__interrupt__")
    assert evidence["distinct_threads"] == 4
    assert evidence["max_overlap"] == 4
    assert evidence["join_runs"] == 1
    assert [result[f"{name}_result"]["status"] for name in CHECKS] == ["ok"] * 4


def test_partial_failure_is_retained_for_analysis(tmp_path: Path) -> None:
    db = tmp_path / "partial.sqlite"
    started = run_cli(db, "partial", "start", "--fault", "fail:service")
    assert started.returncode == 0, started.stderr
    state = inspect(db, "partial")
    assert state["checks"]["service"]["status"] == "failed"
    assert state["checks"]["dns"]["status"] == "ok"
    assert state["values"]["analysis"]["failed_checks"] == ["service"]


def test_transient_retry_succeeds_and_exhaustion_is_bounded(tmp_path: Path) -> None:
    transient = run_cli(tmp_path / "transient.sqlite", "transient", "start",
                        "--fault", "transient:dns")
    assert transient.returncode == 0, transient.stderr
    transient_state = inspect(tmp_path / "transient.sqlite", "transient")
    assert transient_state["checks"]["dns"] == {
        "status": "ok", "detail": "dns mock check passed for lab.example", "attempts": 2}

    exhausted = run_cli(tmp_path / "exhaust.sqlite", "exhaust", "start",
                        "--fault", "exhaust:logs")
    assert exhausted.returncode == 0, exhausted.stderr
    exhausted_state = inspect(tmp_path / "exhaust.sqlite", "exhaust")
    assert exhausted_state["checks"]["logs"]["status"] == "failed"
    assert exhausted_state["checks"]["logs"]["attempts"] == 2


def test_retry_with_all_successes_runs_no_check_and_join_once(tmp_path: Path) -> None:
    db = tmp_path / "all-success.sqlite"
    release = threading.Event()
    entered = threading.Event()
    backend = MockBackends(gate=release, entered=threading.Barrier(4, action=entered.set))
    outputs: list[dict] = []
    runner = threading.Thread(target=lambda: outputs.append(invoke_graph(
        db, "all-success", backend, {"host": "host", "retry_nonce": 0})))
    runner.start()
    assert entered.wait(timeout=10)
    request_cancel(db, "all-success", "finish-at-join")
    release.set()
    runner.join(timeout=15)
    assert not runner.is_alive()
    first = outputs[0]
    assert first["run_status"] == "cancelled_after_diagnostics"
    before = backend.snapshot()["attempts"].copy()
    backend.entered = None
    clear_cancel(db, "all-success")
    retried = invoke_graph(db, "all-success", backend, {"retry_nonce": 1})
    after = backend.snapshot()
    assert retried.get("__interrupt__")
    assert after["attempts"] == before
    assert after["join_runs"] == 2


def test_pre_dispatch_cancel_runs_no_check_and_is_inspectable(tmp_path: Path) -> None:
    db = tmp_path / "pre-cancel.sqlite"
    assert run_cli(db, "pre", "cancel").returncode == 0
    started = run_cli(db, "pre", "start")
    assert started.returncode == 0, started.stderr
    state = inspect(db, "pre")
    assert state["cancel_requested"]["reason"] == "user-request"
    assert state["cancel_observed_at"] == "pre_dispatch"
    assert state["run_status"] == "cancelled_before_dispatch"
    assert all(state["checks"][name]["status"] == "cancelled" for name in CHECKS)


def test_inflight_cancel_observed_at_join_then_retry_only_failed_check(tmp_path: Path) -> None:
    db = tmp_path / "join-cancel.sqlite"
    gate = threading.Event()
    all_entered = threading.Event()
    backend = MockBackends(gate=gate, entered=threading.Barrier(4, action=all_entered.set))
    result_holder: list[dict] = []

    def run_first_attempt():
        result_holder.append(invoke_graph(db, "join-cancel", backend,
                                         {"host": "host", "retry_nonce": 0,
                                          "mock_faults": {"service": "fail"}}))

    runner = threading.Thread(target=run_first_attempt)
    runner.start()
    # The barrier releases only after all four check nodes have entered.
    assert all_entered.wait(timeout=10)
    request_cancel(db, "join-cancel", "test-inflight")
    gate.set()
    runner.join(timeout=15)
    assert not runner.is_alive()
    first = result_holder[0]
    assert first["run_status"] == "cancelled_after_diagnostics"
    assert first["cancel_observed_at"] == "join"
    assert [first[f"{name}_result"]["status"] for name in CHECKS] == [
        "ok", "failed", "ok", "ok"]
    before = backend.snapshot()["attempts"].copy()

    clear_cancel(db, "join-cancel")
    backend.entered = None  # the retry intentionally dispatches only one branch
    retried = invoke_graph(db, "join-cancel", backend,
                           {"retry_nonce": 1, "mock_faults": {"service": "transient"}})
    after = backend.snapshot()["attempts"]
    assert retried.get("__interrupt__")
    assert after["service"] == before["service"] + 2
    assert all(after[name] == before[name] for name in ("dns", "connectivity", "logs"))
    for name in ("dns", "connectivity", "logs"):
        assert retried[f"{name}_result"] == first[f"{name}_result"]
    assert retried["service_result"]["status"] == "ok"


def test_cancelled_finished_thread_retry_reopens_and_approval_resumes_across_processes(
    tmp_path: Path,
) -> None:
    db = tmp_path / "recovery.sqlite"
    thread = "recovery"
    assert run_cli(db, thread, "cancel", "--reason", "before-start").returncode == 0
    assert run_cli(db, thread, "start").returncode == 0
    before = inspect(db, thread)
    assert before["cancel_observed_at"] == "pre_dispatch"
    assert run_cli(db, thread, "retry").returncode == 0
    waiting = inspect(db, thread)
    assert waiting["cancel_requested"] is None
    assert waiting["cancel_observed_at"] is None
    assert waiting["next"] == ["await_approval"]
    approved = run_cli(db, thread, "approve")
    assert approved.returncode == 0, approved.stderr
    done = inspect(db, thread)
    assert done["values"]["execution_status"] == "executed"
    assert done["run_status"] == "completed"


def test_cancel_and_retry_cli_recovery_and_fix_log(tmp_path: Path) -> None:
    db = tmp_path / "cli-demo.sqlite"
    thread = "cli-demo"
    fix_log = tmp_path / "fix.jsonl"
    env = {"W16_FIX_CALL_LOG": str(fix_log)}
    canceled = run_cli(db, thread, "cancel", "--reason", "demo", env_extra=env)
    assert canceled.returncode == 0
    assert run_cli(db, thread, "start", "--host", "lab.example", env_extra=env).returncode == 0
    inspected = inspect(db, thread)
    assert inspected["cancel_requested"] and inspected["cancel_observed_at"] == "pre_dispatch"
    retry = run_cli(db, thread, "retry", env_extra=env)
    assert retry.returncode == 0, retry.stderr
    assert "PENDING APPROVAL" in retry.stdout
    assert run_cli(db, thread, "approve", env_extra=env).returncode == 0
    assert len(fix_log.read_text(encoding="utf-8").splitlines()) == 1


def test_crash_during_parallel_checks_preserves_completed_task_writes_on_cli_retry(
    tmp_path: Path,
) -> None:
    db = tmp_path / "crash-replay.sqlite"
    thread = "crash-replay"
    counters = tmp_path / "check-calls.sqlite"
    gate_dir = tmp_path / "worker-gate"
    gate_dir.mkdir()
    crash_script = r'''import os, sqlite3, sys, threading, time
from pathlib import Path
from contextlib import closing
from langgraph.checkpoint.sqlite import SqliteSaver
from langsmith import tracing_context
from long_running_workflow_lab.workflow import MockBackends, build_graph, checkpoint_connection

db, thread, counters, gate_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
def record(name):
    with sqlite3.connect(counters, timeout=5.0) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS check_calls (name TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.execute("INSERT INTO check_calls(name, calls) VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET calls = calls + 1", (name,))
        connection.commit()
class CrashBackend(MockBackends):
    def check(self, name, host, attempt, faults):
        record(name)
        detail = super().check(name, host, attempt, faults)
        if name == "dns":
            ready = gate_dir / "target-ready"
            with ready.open("w", encoding="utf-8") as stream:
                stream.write("dns backend finished; node update not returned")
                stream.flush()
                os.fsync(stream.fileno())
            deadline = time.monotonic() + 20
            while not (gate_dir / "release-crash").exists():
                if time.monotonic() >= deadline:
                    os._exit(87)
                time.sleep(0.01)
            os._exit(86)
        return detail
connection = checkpoint_connection(db)
with closing(connection), tracing_context(enabled=False):
    graph = build_graph(db, SqliteSaver(connection), CrashBackend(entered=threading.Barrier(4)))
    graph.invoke({"host": "lab.example", "retry_nonce": 0},
                 config={"configurable": {"thread_id": thread}}, durability="sync")
'''
    env = os.environ.copy()
    env.update({
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join((str(PROJECT_DIR / "src"), str(PROJECT_DIR / "tests"))),
    })
    child = subprocess.Popen(
        [sys.executable, "-c", crash_script, str(db), thread, str(counters), str(gate_dir)],
        cwd=PROJECT_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        ready_deadline = time.monotonic() + 15
        while not (gate_dir / "target-ready").exists() and time.monotonic() < ready_deadline:
            if child.poll() is not None:
                stdout, stderr = child.communicate(timeout=5)
                pytest.fail(f"crash worker exited before the barrier: {child.returncode}\n{stdout}\n{stderr}")
            time.sleep(0.01)
        assert (gate_dir / "target-ready").exists(), "crashing check did not reach the barrier"

        committed = set()
        writes_deadline = time.monotonic() + 15
        expected_committed = set(CHECKS) - {"dns"}
        while time.monotonic() < writes_deadline:
            committed = persisted_check_writes(db, thread)
            if expected_committed.issubset(committed):
                break
            time.sleep(0.025)
        assert expected_committed.issubset(committed), (
            f"expected durable writes for {sorted(expected_committed)}, found {sorted(committed)}"
        )
        assert check_call_counts(counters) == {name: 1 for name in CHECKS}
        (gate_dir / "release-crash").write_text("crash now", encoding="utf-8")
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 86, f"expected intentional crash 86, got {child.returncode}\n{stdout}\n{stderr}"
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)

    # A new process can inspect the same checkpoint and sees runnable work.
    before = inspect(db, thread)
    assert before["run_status"] == "diagnosing"
    assert "dns" in before["next"]
    assert persisted_check_writes(db, thread) == set(CHECKS) - {"dns"}
    calls_before_retry = check_call_counts(counters)

    # This is the production CLI retry route. Pending work uses invoke(None);
    # the instrumentation writes every actual backend call to durable SQLite.
    retried = instrumented_cli(db, thread, counters, "retry")
    assert retried.returncode == 0, retried.stderr
    assert "PENDING APPROVAL" in retried.stdout
    inputs = [json.loads(line) for line in counters.with_suffix(".inputs.jsonl").read_text().splitlines()]
    assert inputs == [{"kind": "none"}]
    after = inspect(db, thread)
    assert after["next"] == ["await_approval"]
    assert all(after["checks"][name]["status"] == "ok" for name in CHECKS)
    assert calls_before_retry == {name: 1 for name in CHECKS}
    assert check_call_counts(counters) == {**calls_before_retry, "dns": 2}


def test_finished_thread_invoke_none_is_noop_but_cli_retry_uses_fresh_input(
    tmp_path: Path,
) -> None:
    db = tmp_path / "finished-retry.sqlite"
    thread = "finished-retry"
    counters = tmp_path / "finished-calls.sqlite"

    assert run_cli(db, thread, "cancel", "--reason", "finish-before-start").returncode == 0
    started = run_cli(db, thread, "start", "--host", "lab.example")
    assert started.returncode == 0, started.stderr
    finished = inspect(db, thread)
    assert finished["next"] == []
    assert finished["values"]["retry_nonce"] == 0

    # LangGraph itself treats invoke(None) on this terminal snapshot as a no-op.
    connection = checkpoint_connection(db)
    backend = MockBackends()
    with closing(connection), tracing_context(enabled=False):
        graph = build_graph(db, SqliteSaver(connection), backend)
        graph.invoke(None, config={"configurable": {"thread_id": thread}}, durability="sync")
        no_op_snapshot = graph.get_state({"configurable": {"thread_id": thread}})
    assert no_op_snapshot.next == ()
    assert backend.snapshot()["attempts"] == {}

    # CLI retry distinguishes the finished thread and supplies nonce + 1 as fresh input.
    retried = instrumented_cli(db, thread, counters, "retry")
    assert retried.returncode == 0, retried.stderr
    inputs = [json.loads(line) for line in counters.with_suffix(".inputs.jsonl").read_text().splitlines()]
    assert inputs == [{"kind": "input", "value": {"retry_nonce": 1}}]
    after = inspect(db, thread)
    assert after["values"]["retry_nonce"] == 1
    assert after["next"] == ["await_approval"]
    assert all(after["checks"][name]["status"] == "ok" for name in CHECKS)
    assert check_call_counts(counters) == {name: 1 for name in CHECKS}
