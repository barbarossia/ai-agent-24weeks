# Portfolio evidence

This directory contains local, reproducible evidence for the Week-24 lab. It uses only the synthetic cases shipped in `evals/golden.jsonl`.

- [Eval results](eval-run/eval-results.json): 3 of 3 cases passed. Each case verifies the cited cause and action, accepted review, runtime approval record, ten read calls, one simulated write, recovery, report, and absence of a capability in trace output.
- [Reports](eval-run/reports/): one source-cited troubleshooting report per case.
- [Traces](eval-run/traces/): JSONL workflow and MCP spans for each eval case.
- [Metrics](eval-run/metrics/): per-case counters and duration summaries.
- [Interactive approval demo](operator-demo/transcript.txt): a complete proxy-route diagnosis, approval prompt, and recovery report. The run received `approve` and the approver label `portfolio-operator` through stdin; the CLI does not echo typed input. The clean [report](operator-demo/report.md) is also available separately.
- [Approval demo trace](operator-demo/trace.jsonl) and [metrics](operator-demo/metrics.json).
- [Security model](security-model.md) and [Compose verification](compose-verification.md).

The pass/fail summary is deterministic. Trace span durations are observed local timings and can vary between runs.
