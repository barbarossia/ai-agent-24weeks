# Week 18: Agent Observability Lab

A standard-library, offline lab for request tracing, Prometheus-compatible metrics, and repeatable fault scenarios. It reuses the Week 12/17 design seams conceptually (agent step, LLM call, tool call, deterministic doubles) while remaining isolated from those weeks. It makes no network, device, MCP, credential, or model-service calls.

## Run

From this directory, use `python -m venv .venv && . .venv/bin/activate && pip install -e .` (pytest is a development dependency) and then:

```sh
week18-observe
week18-observe --fault slow --format json
week18-observe --fault retry --format prometheus
week18-observe --fault failure
pytest -q
```

`none`, `slow`, `failure`, and `retry` are deterministic. Slow mode reports synthetic latency and does not sleep. Failure exits 1; retry injects one LLM failure followed by success. `--format prometheus` prints scrape text; `--format json` prints the safe summary and spans.

## Signals

Spans form `request → agent.step → {llm, tool}` parent/child trees and carry only allow-listed operation/outcome/attempt/token/cost/fault attributes. Prompt, response, arguments, user identifiers, and exception text are excluded. Trace/span identifiers are generated per run.

Metrics expose request and error counters, operation latency histograms, synthetic token totals, and synthetic USD cost totals. Labels are restricted to fixed `operation` and `status` enums; do not add request IDs, user data, tool names from input, or other unbounded values.

Import `dashboards/week18-agent-observability.json` into Grafana and configure a Prometheus data source that scrapes the CLI output via an external local collector if desired. The lab itself does not host an HTTP scrape endpoint or start Grafana/Prometheus.

## Limits and review

The span exporter and metrics registry are in-memory examples, not production OpenTelemetry SDK/exporters or an HTTP server. Latency, token usage, and price are fixed synthetic estimates; the tool is a local stub. Trace IDs are intentionally nondeterministic, while scenario outcomes and synthetic latency are deterministic. Review label allow-lists and privacy guarantees before adapting this demo to real telemetry.
