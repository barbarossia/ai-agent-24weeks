# Week 18 verification evidence

All checks ran offline from this directory; no credentials, network, model, MCP, or device services were used.

- `python3 -m pytest -q -p no:cacheprovider` — **5 passed**.
- `python3 -m json.tool dashboards/week18-agent-observability.json` — **valid JSON**.
- `PYTHONPATH=src python3 -m week18_observability_lab --fault slow --format summary` — `status=success fault=slow spans=4 synthetic_latency_ms=126`.
- `PYTHONPATH=src python3 -m week18_observability_lab --fault retry --format prometheus` — emitted Prometheus counters/histograms, including one LLM error and one LLM success; labels limited to operation/status.
- `PYTHONPATH=src python3 -m week18_observability_lab --fault failure --format prometheus` — emitted error series and exits 1 as expected for injected failure.

Tests cover request → agent step → LLM/tool parent-child relationships, safe attribute filtering (including rejection of unbounded span names and values), bounded metric labels, histogram exposition, and deterministic slow/failure/retry behavior. An initial pytest invocation passed but emitted a cache write warning because pytest attempted an unapproved cache directory; the recorded no-cache-provider run is clean.

## Reviewer follow-ups

- Confirm the allow-listed span fields and metric labels remain appropriate before any real telemetry integration.
- Decide whether a future lab should add an HTTP scrape endpoint or OpenTelemetry SDK/exporter; neither is included here.
- Synthetic duration/token/cost values are teaching fixtures, not production measurements or billing estimates.
