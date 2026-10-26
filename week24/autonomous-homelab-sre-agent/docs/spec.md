# Week 24 Lab Specification

## Objective

Build a standalone, deterministic portfolio lab for diagnosing the simulated incident “Netflix cannot be reached.” The workflow retrieves cited facts from a small Obsidian-style vault, runs DNS, proxy, node, routing-rule, and log checks through custom read-only MCP tools, correlates evidence, proposes a bounded fix, waits for explicit human approval, applies only an approved in-memory simulation, verifies recovery, and produces a source-cited troubleshooting report.

## Stack and commands

- Python 3.12+
- Official MCP Python SDK 2.x over local stdio subprocesses
- LangGraph 1.x with SQLite checkpoints
- pytest and pytest-asyncio for deterministic offline behavior
- Docker Compose with networking disabled for the lab container

From this directory:

```sh
uv sync --locked
uv run pytest
uv run w24-sre eval
uv run w24-sre demo --case proxy-rule-mismatch
docker compose config --quiet
docker compose run --rm lab eval
```

## Structure

```text
src/autonomous_homelab_sre_agent/  workflow, MCP clients/servers, policy, telemetry, CLI
vault/knowledge/                    synthetic Obsidian Markdown runbooks
evals/                               fixed golden scenarios and expected outcomes
tests/                               offline unit, MCP, workflow, and eval checks
evidence/                            eval results, reports, traces, and security evidence
docs/                                this specification and architecture notes
```

## Core state and workflow

The checkpointed state contains the normalized incident, retrieved citations, read-only observations, two typed specialist-agent handoffs, a proposed action, approval decision, simulated action result, verification observations, and final report. Graph nodes run in this order:

1. Understand the request and constrain it to the supported Netflix fixture.
2. Retrieve relevant local runbook sections and mark/remove instruction-like untrusted text.
3. Call five fixture-only read tools: DNS, proxy, node, rule, and logs.
4. Let the diagnostic specialist identify a cause from structured evidence; let an independent reviewer require corroboration and a cited runbook.
5. Propose one scenario allowlisted simulated action.
6. Interrupt and checkpoint before any write-capable MCP process is started. The evaluator confirms each approved run received this interrupt, plus separate paused and rejected runs with zero write calls.
7. On a matching explicit approval, issue a one-run capability and call the isolated simulated-write MCP tool. On reject, stop without calling it.
8. Re-run the same five read-only checks with the returned simulation overlay, then render a report.

LangGraph interrupts restart their node when resumed. The approval node therefore has no effects before its interrupt. The only remediation caller is a later node which validates the resumed decision, binds it to the exact proposal digest, and only then starts the write server. The write server independently requires a short-lived capability that is never checkpointed or traced.

## Boundaries

- **Always:** use fixed local fixtures; validate all case IDs and action IDs; keep retrieved Markdown and logs untrusted; cite each runbook claim; require corroborating evidence; checkpoint graph state; trace tool and node outcomes without raw secrets; require an explicit approval value before the simulated-write MCP process exists.
- **Ask first:** any future integration that accesses a real DNS resolver, proxy, node, rule store, log service, external MCP endpoint, or knowledge vault; any real remediation; any dependency that requires credentials or network access at runtime.
- **Never:** access HomeClash, live homelab services, credentials/secrets, or the separate homelab-mcp repository; expose a real remediation tool; interpret retrieved text as policy; execute shell commands from agent output; modify the repository root `.gitignore`.

Report export is a separate, optional CLI action that requires its own interactive confirmation. It writes under `vault/knowledge/reports/`, which is included in subsequent local retrieval. Normal demos and evals write only local checkpoint/trace/eval artifacts under the selected data directory.

## Verification strategy

- Unit checks cover request bounds, allowlists, injection handling, retrieval provenance, evidence correlation, proposal binding, and metrics/traces.
- MCP tests verify the actual tool inventory for each server role and reject missing/invalid write capabilities.
- Workflow tests cover interrupt/checkpoint/resume, approval, rejection, no approval, exactly one approved write call, and post-action recovery.
- The golden eval contains at least three complete cases and asserts cause, evidence, citations, tool order, approval-interrupt observation, recovery, and report fields. Separate pause and rejection fixtures assert zero writes.
- Compose verification checks the resolved configuration and runs the offline eval container with no network and a read-only root filesystem.

## Success criteria

- No external model, API, service, credentials, or network access is needed to run the demos.
- Every diagnosis has multiple independent evidence references and a cited local Obsidian source.
- Five named read checks run before and after an approved action.
- No write MCP process/tool call occurs before a matching runtime approval; rejected and paused runs do not write.
- Three complete offline eval demos pass deterministically and emit trace, metrics, and report evidence. Pass/fail summaries and reports are deterministic; measured trace and metric durations vary by run.
- Docker Compose can run the evals with network disabled and permission-separated simulation boundaries.
