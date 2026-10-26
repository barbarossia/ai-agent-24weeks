from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class TraceRecorder:
    def __init__(self, run_id: str):
        if not SAFE_ID.fullmatch(run_id):
            raise ValueError("run_id must contain only letters, numbers, underscores, and hyphens")
        self.run_id = run_id
        self._next_span = 0
        self.spans: list[dict[str, Any]] = []
        self.counters: Counter[str] = Counter()
        self.duration_ms: defaultdict[str, float] = defaultdict(float)
        self._tool_started: dict[str, tuple[float, str | None]] = {}
        self._active_spans: list[str] = []

    @contextmanager
    def span(self, name: str, **attributes: str | int | float | bool) -> Iterator[None]:
        self._next_span += 1
        span_id = f"{self.run_id}-{self._next_span:04d}"
        parent_span_id = self._active_spans[-1] if self._active_spans else None
        self._active_spans.append(span_id)
        started = time.perf_counter()
        status = "ok"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            self.duration_ms[name] += elapsed
            self._active_spans.pop()
            self.spans.append({
                "trace_id": self.run_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "status": status,
                "duration_ms": elapsed,
                "attributes": attributes,
            })
            self.counters[f"spans_total|name={name}|status={status}"] += 1

    def tool_event(self, tool: str, outcome: str) -> None:
        if outcome == "started":
            parent_span_id = self._active_spans[-1] if self._active_spans else None
            self._tool_started[tool] = (time.perf_counter(), parent_span_id)
            return
        if outcome not in {"ok", "error"}:
            return
        started, parent_span_id = self._tool_started.pop(tool, (time.perf_counter(), None))
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        self.counters[f"mcp_tool_calls_total|tool={tool}|outcome={outcome}"] += 1
        self.duration_ms[f"mcp.{tool}"] += elapsed
        self._next_span += 1
        self.spans.append({
            "trace_id": self.run_id,
            "span_id": f"{self.run_id}-{self._next_span:04d}",
            "parent_span_id": parent_span_id,
            "name": f"mcp.{tool}",
            "status": outcome,
            "duration_ms": elapsed,
            "attributes": {"tool": tool},
        })

    def increment(self, metric: str, **labels: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,80}", metric):
            raise ValueError("invalid metric name")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", key) for key in labels):
            raise ValueError("invalid metric label")
        values = "|".join(f"{key}={labels[key]}" for key in sorted(labels))
        self.counters[f"{metric}|{values}" if values else metric] += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "counters": dict(sorted(self.counters.items())),
            "duration_ms": {key: round(value, 3) for key, value in sorted(self.duration_ms.items())},
        }

    def prometheus_text(self) -> str:
        metric_names = {
            "spans_total": "w24_agent_spans_total",
            "mcp_tool_calls_total": "w24_mcp_tool_calls_total",
            "workflow_runs_total": "w24_workflow_runs_total",
            "approval_decisions_total": "w24_approval_decisions_total",
            "simulated_remediations_total": "w24_simulated_remediations_total",
            "knowledge_redactions_total": "w24_knowledge_redactions_total",
        }
        lines: list[str] = []
        for key, value in sorted(self.counters.items()):
            parts = key.split("|")
            metric = metric_names.get(parts[0])
            if not metric:
                continue
            labels = []
            for item in parts[1:]:
                name, _, label_value = item.partition("=")
                escaped = label_value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                labels.append(f'{name}="{escaped}"')
            suffix = "{" + ",".join(labels) + "}" if labels else ""
            lines.append(f"{metric}{suffix} {value}")
        for name, value in sorted(self.duration_ms.items()):
            escaped = name.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'w24_span_duration_ms_sum{{span="{escaped}"}} {value:.3f}')
        return "\n".join(lines) + ("\n" if lines else "")

    def write(self, output_dir: Path) -> tuple[Path, Path]:
        output_dir = output_dir.resolve()
        trace_dir = output_dir / "traces"
        metrics_dir = output_dir / "metrics"
        trace_dir.mkdir(parents=True, exist_ok=True)
        metrics_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / f"{self.run_id}.jsonl"
        metrics_path = metrics_dir / f"{self.run_id}.json"
        with trace_path.open("w", encoding="utf-8") as stream:
            for span in self.spans:
                stream.write(json.dumps(span, sort_keys=True) + "\n")
        metrics_path.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return trace_path, metrics_path

    @classmethod
    def restore(cls, output_dir: Path, run_id: str) -> TraceRecorder:
        recorder = cls(run_id)
        trace_path = output_dir / "traces" / f"{run_id}.jsonl"
        metrics_path = output_dir / "metrics" / f"{run_id}.json"
        if trace_path.is_file():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    recorder.spans.append(json.loads(line))
            recorder._next_span = len(recorder.spans)
        if metrics_path.is_file():
            data = json.loads(metrics_path.read_text(encoding="utf-8"))
            recorder.counters.update(data.get("counters", {}))
            recorder.duration_ms.update(data.get("duration_ms", {}))
        return recorder
