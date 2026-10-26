"""Deterministic HTTP eval and state/observability recovery checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import ssl
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _request(
    url: str, *, method: str = "GET", body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None, context: ssl.SSLContext | None = None,
) -> tuple[int, dict[str, Any] | str, dict[str, str]]:
    request_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, context=context, timeout=3) as response:
            raw = response.read()
            status = response.status
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as error:
        raw = error.read()
        status = error.code
        response_headers = {key.lower(): value for key, value in error.headers.items()}
    except URLError as error:
        raise RuntimeError(f"request failed for {url}: {error.reason}") from error
    content_type = response_headers.get("content-type", "")
    payload: dict[str, Any] | str
    if "json" in content_type:
        payload = json.loads(raw.decode())
    else:
        payload = raw.decode()
    return status, payload, response_headers


def _wait_ready(base_url: str, context: ssl.SSLContext, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            live = _request(f"{base_url}/health/live", context=context)
            ready = _request(f"{base_url}/health/ready", context=context)
            if live[0] == 200 and ready[0] == 200:
                return
            last_error = RuntimeError(f"live={live[0]}, ready={ready[0]}")
        except (RuntimeError, OSError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(f"API did not become ready: {last_error}")


def _context(ca_file: Path) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca_file))


def _case_trace(name: str) -> tuple[str, str, str]:
    trace_id = hashlib.sha256(f"trace:{name}".encode()).hexdigest()[:32]
    span_id = hashlib.sha256(f"span:{name}".encode()).hexdigest()[:16]
    return trace_id, span_id, f"00-{trace_id}-{span_id}-01"


def run_eval(base_url: str, context: ssl.SSLContext, dataset: Path, state_file: Path) -> dict[str, Any]:
    _wait_ready(base_url, context)
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    task_records: list[dict[str, str]] = []
    for case in cases:
        trace_id, _, traceparent = _case_trace(case["name"])
        status, created, response_headers = _request(
            f"{base_url}/v1/tasks", method="POST",
            body={"operation": case["operation"], "input": case["input"]},
            headers={"traceparent": traceparent}, context=context,
        )
        assert status == 201, f"{case['name']}: expected 201, received {status}: {created}"
        assert isinstance(created, dict)
        assert created["status"] == "completed"
        assert created["result"] == case["expected_result"], case["name"]
        assert created["trace_id"] == trace_id, case["name"]
        assert response_headers.get("x-trace-id") == trace_id, case["name"]

        task_id = created["id"]
        get_status, fetched, _ = _request(f"{base_url}/v1/tasks/{task_id}", context=context)
        assert get_status == 200 and isinstance(fetched, dict), case["name"]
        assert fetched["result"] == case["expected_result"], case["name"]
        task_records.append({"id": task_id, "trace_id": trace_id, "name": case["name"]})

    _, metrics, _ = _request(f"{base_url}/metrics", context=context)
    assert isinstance(metrics, str)
    for operation in {case["operation"] for case in cases}:
        assert f'agent_task_requests_total{{operation="{operation}"}}' in metrics

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"tasks": task_records}, indent=2) + "\n", encoding="utf-8")
    return {"passed": len(cases), "tasks": task_records}


def verify_state(base_url: str, context: ssl.SSLContext, state_file: Path) -> dict[str, Any]:
    _wait_ready(base_url, context)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    for task in state["tasks"]:
        status, record, _ = _request(f"{base_url}/v1/tasks/{task['id']}", context=context)
        assert status == 200 and isinstance(record, dict), f"task {task['id']} did not survive restart"
        assert record["id"] == task["id"] and record["status"] == "completed"
        assert record["trace_id"] == task["trace_id"], f"task {task['id']} trace changed"
    return {"persisted": len(state["tasks"]), "state_file": str(state_file)}


def verify_request_logs(log_file: Path, state_file: Path) -> dict[str, int]:
    state = json.loads(state_file.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        payload = line.split("|", maxsplit=1)[-1].strip()
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("event") == "http_request":
            records.append(record)

    assert records, "API container logs contained no structured http_request records"
    for record in records:
        assert isinstance(record.get("duration_ms"), (int, float)), record
        assert isinstance(record.get("trace_id"), str) and len(record["trace_id"]) == 32, record

    for task in state["tasks"]:
        assert any(
            record.get("method") == "POST"
            and record.get("route") == "/v1/tasks"
            and record.get("status") == 201
            and record.get("trace_id") == task["trace_id"]
            for record in records
        ), f"API logs did not contain correlated creation request for {task['name']}"
    assert any(
        record.get("method") == "GET"
        and record.get("route") == "/v1/tasks/{task_id}"
        and record.get("status") == 200
        for record in records
    ), "API logs did not contain a normalized task retrieval request"
    return {
        "http_request_logs": len(records),
        "correlated_task_creates": len(state["tasks"]),
    }


def verify_observability(
    context: ssl.SSLContext, state_file: Path, prometheus_url: str, jaeger_url: str,
) -> dict[str, int]:
    state = json.loads(state_file.read_text(encoding="utf-8"))
    traces = 0
    deadline = time.monotonic() + 30
    remaining = {task["trace_id"] for task in state["tasks"]}
    while remaining and time.monotonic() < deadline:
        for trace_id in list(remaining):
            status, body, _ = _request(f"{jaeger_url}/api/traces/{trace_id}")
            if status == 200 and isinstance(body, dict) and body.get("data"):
                remaining.remove(trace_id)
                traces += 1
        if remaining:
            time.sleep(1)
    assert not remaining, f"Jaeger did not receive correlated traces: {sorted(remaining)}"

    prometheus_query = quote('up{job="agent-api"}', safe="")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, body, _ = _request(f"{prometheus_url}/api/v1/query?query={prometheus_query}")
        if status == 200 and isinstance(body, dict):
            result = body.get("data", {}).get("result", [])
            if result and result[0].get("value", [None, "0"])[1] == "1":
                return {"jaeger_traces": traces, "prometheus_targets_up": len(result)}
        time.sleep(1)
    raise AssertionError("Prometheus did not report the agent-api target as up")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://localhost:8443")
    parser.add_argument("--ca-file", type=Path, default=Path("secrets/local-tls.crt"))
    parser.add_argument("--dataset", type=Path, default=Path("evals/cases.json"))
    parser.add_argument("--state-file", type=Path, default=Path(".local/eval-state.json"))
    parser.add_argument("--verify-state-file", type=Path)
    parser.add_argument("--verify-log-file", type=Path)
    parser.add_argument("--verify-observability", action="store_true")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--jaeger-url", default="http://localhost:16686")
    args = parser.parse_args()
    try:
        context = _context(args.ca_file)
        if args.verify_state_file:
            result = verify_state(args.base_url, context, args.verify_state_file)
            state_file = args.verify_state_file
        else:
            result = run_eval(args.base_url, context, args.dataset, args.state_file)
            state_file = args.state_file
        if args.verify_log_file:
            result["request_logs"] = verify_request_logs(args.verify_log_file, state_file)
        if args.verify_observability:
            result["observability"] = verify_observability(
                context, state_file, args.prometheus_url, args.jaeger_url,
            )
    except (AssertionError, OSError, RuntimeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps({"result": "PASS", **result}, indent=2))


if __name__ == "__main__":
    main()
