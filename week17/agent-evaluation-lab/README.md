# Week 17 — Agent Evaluation Lab (offline, deterministic)

A credential-free, network-free, database-free offline evaluation of the **real
Week 12 `KnowledgeAgent`** driven through its real injectable seams. It runs the
real `homelab_knowledge_agent.agent.KnowledgeAgent` and the real
`homelab_knowledge_agent.homelab.MockHomeLab.collect()`, replacing only the RAG
and generation seams with scripted doubles and runtime-patching the MCP transport
(`homelab.stdio_client`, `homelab.ClientSession`) and the clock
(`homelab.datetime`). Week 12 source is never edited.

## Fixed-contract disclaimer (required, verbatim)

> the evaluated agent performs a **fixed** `ping→get_health_status` sequence coded in
> Week 12; no component selects tools or arguments per question, therefore
> Week 17 measures **integration-allowlist conformance and argument-shape
> accuracy** (empty `{}`), *not dynamic per-question tool selection*.

The Week 17 note box `能测 Tool selection` is intentionally **unchecked**:
Week 17 tests fixed-contract tool/argument conformance only. This lab never
claims dynamic tool selection.

## What is measured (and what is not)

- **Measured**: retrieval-to-prompt contract, the fixed MCP tool/argument
  allowlist contract, generation-seam contract, prompt/provenance composition,
  per-stage pass/failure pinpointing, aggregate metrics, and byte-level
  determinism of the compared artifacts.
- **Not measured**: semantic answer quality. Generation is a deterministic
  scripted template; the answer-token checks are therefore **deterministic
  contract/evidence checks, not semantic-quality scores**. RAG rows are
  scripted fixtures (`fixture/…`), not a live retrieval result.

## Dataset

`data/golden_eval.jsonl` — exactly **30 sanitized fixture records** (10 `network`,
10 `docker`, 10 `esxi`), one JSON object per line, `schema_version: "1"`. IDs are
`W17-{NET,DOC,ESX}-NNN`. The strict validator (pydantic, `extra=forbid`) rejects
wrong totals/per-category counts, unknown/duplicate IDs, category↔prefix
mismatch, empty/oversized questions, out-of-contract `tool_sequence`, malformed
retrieval fixtures, and caps violations.

### Sanitizer screen (record level)

The screen runs at the **record level**, covering every free-text surface:
`question`, `notes`, each `tags[]` entry, and every `fixture.rag_rows[]`
`source_path` / `heading_path` / `content`. It rejects:

- credential/token/key/password/secret/`bearer` strings (`name=value` and `bearer …`);
- email addresses;
- user home paths (`/Users/…`, `/home/…`, `C:\Users\…`);
- private/internal IP literals (RFC1918 `10/8`, `172.16/12`, `192.168/16`, plus
  loopback `127/8` and link-local `169.254/16`);
- any RAG `source_path` not beginning with `fixture/`.

**Known limits (no overclaim):** the screen does **not** detect personal names,
organization names, or other free-form private text, because high-signal patterns
are deliberately conservative to avoid false positives on legitimate fixtures.
Sanitization remains a review responsibility, not a guarantee.

## Determinism policy

- A frozen clock (`FrozenDatetime.now(cls, tz=None)` → constant
  `2026-01-01T00:00:00+00:00`) is patched onto the `homelab` module so the two
  timestamp occurrences (MCP `fetched_at`, final-answer provenance) are constant.
- Compared artifacts (**`report.json` + `trajectory.jsonl`**) contain no wall
  clock or durations; every JSON write uses `sort_keys=True`. Two consecutive
  `week17-eval run` invocations must produce byte-identical compared artifacts.
- The only volatile file is `run_meta.json` (start/finish/durations), written
  beside the artifacts but **excluded from comparison and gitignored**. Absolute
  home paths are never written into compared artifacts.

## Commands and exit codes

```bash
cd week17/agent-evaluation-lab
uv sync --dev

# 0 = valid, 2 = validation failure, 1 = unexpected (redacted)
uv run week17-eval validate --dataset data/golden_eval.jsonl

# Equivalent module entry point (python -m): same CLI and exit codes
uv run python -m week17_agent_evaluation_lab validate --dataset data/golden_eval.jsonl

# 0 = ran with no contract violations, 2 = violations (with --fail-on-violation), 1 = unexpected
uv run week17-eval run --dataset data/golden_eval.jsonl --out results/ [--fail-on-violation]

# Manual (human) Judge seam — separate from the deterministic offline score
uv run week17-eval judge --prepare --case W17-ESX-003 --out judge/packets
uv run week17-eval judge --record judge/verdicts/W17-ESX-003.json

uv run pytest -q
```

**Exit-code distinction:** invalid dataset *content* (wrong count, bad category,
sanitizer hit, …) exits **2**; an unexpected runtime error such as a missing
`--dataset` file exits **1** with a redacted message. Both are intentional: 2
means "the data/contract is wrong", 1 means "the tool could not run".

## Manual Judge seam (separate, human-only, credential-free)

`judge --prepare` writes one **redacted** packet (question, fixture knowledge rows,
the deterministic canned answer, and contract evidence only — no tokens, no raw
JSON-RPC, no environment). A human may later run the real Week 12 `ask` **outside
CI** and record a verdict via `judge --record`; the verdict schema requires
`verdict_source`. The shipped demonstration verdict uses
`"verdict_source": "user-supplied-example"`:

> 示例判定为用户提供的样例（仅验证 Judge schema 与流程），本轮未调用任何模型；
> Judge 路径与确定性离线评测分离，离线指标不依赖 Judge。

No model credential is read, logged, or committed anywhere in this lab.

## Offline isolation (no network/process/DB by design)

`tests/conftest.py` clones Week 12's `offline_only` guards (socket
`connect`/`create_connection`, `asyncio.create_subprocess_exec`,
`psycopg.connect`) with **no per-test lifts**. The fake MCP session replaces the
transport before any process or socket exists. `psycopg` is never contacted
(RAG rows are inline).

Residual disclosed honestly: no Week 17 test composes **real transport × real
`MockHomeLab.collect()`** in one flow. The server-process boundary is covered by
the existing suites — Week 8 `tests/test_integration.py` (real stdio round-trip)
and Week 12 `tests/test_integrations.py` (real `collect()` over faked transport).

## Scope / path deviation (honest record)

The Week 17 note 实战 line says `建立 /tests/evals/`. The actual landing is
`week17/agent-evaluation-lab/tests/evals/` + `data/golden_eval.jsonl`, following
the per-lab independent-directory and pytest `testpaths = ["tests"]` convention;
**no repository-root `tests/` is created**. The "30 个真实问题" wording is
recorded as 30 **sanitized fixture** questions (policy: no real operational data).

## CI

`.github/workflows/week17-eval.yml` is the repository's **first** workflow. It
runs validation, the offline test suite, the evaluation, and uploads the result
artifacts. It performs no model, HomeLab or database call, and uses no secrets.
Because this ticket does not commit/push, the workflow is **locally simulated
only**; the first observed GitHub Actions run is pending a human push/PR.
