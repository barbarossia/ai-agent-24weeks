# Portfolio evidence

This directory contains local, reproducible evidence for the Week-24 lab. It uses only the synthetic cases shipped in `evals/golden.jsonl` and `evals/approval-gate.jsonl`.

- [Eval results](eval-run/eval-results.json): 3 of 3 complete diagnosis cases passed, plus explicit pause and rejection gate checks. Approved cases verify the observed interrupt, cited cause/action, review, ten read calls, one simulated write, recovery, report, and no capability in traces. Pause/reject cases each verify zero writes.
- [Reports](eval-run/reports/): one source-cited troubleshooting report per case.
- [Traces](eval-run/traces/): JSONL workflow and MCP spans for each recovery and approval-gate case.
- [Metrics](eval-run/metrics/): per-case counters and duration summaries.
- [Interactive approval demo](operator-demo/transcript.txt): a complete proxy-route diagnosis, approval prompt, and recovery report. The run received `approve` and the approver label `portfolio-operator` through stdin; the CLI does not echo typed input. The clean [report](operator-demo/report.md) is also available separately.
- [Approval demo trace](operator-demo/trace.jsonl) and [metrics](operator-demo/metrics.json).
- [Security model](security-model.md) and [Compose verification](compose-verification.md).

The pass/fail summary and reports are deterministic. Trace span durations and metric durations are observed local timings and can vary between runs.
