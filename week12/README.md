# Week 12 — HomeLab Knowledge Agent

One local question combines existing Week 11 Obsidian retrieval with a read-only Week 8 MCP health result, then asks an OpenAI model through Codex App Server to synthesize the evidence. The output always includes retrieved source paths/headings and a **MockAdapter** label. “MCP live data” means a fresh MCP call for the current request; these are sample values, not measurements from real HomeLab devices.

## Setup and question command

Use Python 3.12+ and uv from this directory in the repository checkout. The Week 11 project must exist alongside Week 8/9; the Week 12 work branch is based on `feature/week11-obsidian-knowledge-agent` for that reason.

```powershell
cd week12
uv sync --dev
uv run python -m homelab_knowledge_agent --help
uv run python -m homelab_knowledge_agent auth-status
uv run python -m homelab_knowledge_agent ask "What should I check when my HomeLab datastore is unhealthy?" --model gpt-6-sol --source-path integration-test/week12-demo/note.md
```

The last command requires an **existing** configured Week 11 mock corpus and an available ChatGPT-managed Codex model. The sample source identity must already refer to a sanitized note; change it to another known sanitized source if needed. An empty source match is reported as no knowledge, not a successful retrieval demonstration. Omitting `--source-path` searches the existing corpus; do that only when those notes are appropriate to send to the model. `--top-k` is 1–5 (default 3); repeated `--tag` uses Week 11's ANY matching semantics.

Connection configuration is read only from the existing `W11_DATABASE_URL`, or `PGSERVICE`, or all of `PGHOST`, `PGDATABASE`, `PGUSER`. Existing libpq authentication can supply the connection credentials. No secret values belong in command arguments or source files. The CLI does not discover configuration files, inspect container environments, load `.env` files, create credentials or guess a connection. Missing configuration stops the command before MCP/model execution. Use `W11_PROVIDER=mock` (default) and the dimension of the existing mock schema via `W11_DIMENSION` (default 128).

The generator requires Codex CLI on PATH and accepts **only managed ChatGPT authentication**. `auth-status` uses App Server `account/read` and prints no account identity or tokens. See [authenticated smoke procedure](docs/openai-smoke.md) for login and validation. An API key is never requested, forwarded or used; external-token and alternate-provider fallbacks are absent. `--model` is explicit so the account's chosen model is not silently substituted. Model access, network and usage limits may still block generation after an auth check succeeds.

## Data flow and reuse

1. Week 11's `PgStore.search` executes real SQL inside a PostgreSQL **READ ONLY** transaction with a 10-second statement timeout. Its schema/provider checks still apply. Week 12 never invokes init, migration, index or delete.
2. The MCP SDK launches the existing Week 8 stdio server using this environment's Python. Its environment explicitly sets `HOMELAB_MODE=mock` and excludes OpenWrt configuration. Only `ping` and `get_health_status` are called, with mock/read-only mode verified before health retrieval. MCP calls time out after 30 seconds.
3. The bounded evidence and recent conversation are sent through supported App Server JSONL: initialize, managed account check, fresh ephemeral thread, turn, final completion. A failed turn never becomes a successful answer. Request/response messages and raw stderr are not logged.
4. The model's synthesized answer is returned with source provenance and the current-request MockAdapter disclosure. Model factual quality still needs human evaluation; provenance alone does not prove its reasoning is correct.

Week 11 reuses Week 9's `MockEmbeddingProvider`; Week 12 imports that existing provider contract and adds no embedding service. **Mock vectors establish deterministic retrieval pipeline behavior only, not production semantic quality.** Week 9's demo/in-memory PgVectorStore is not used. Local editable dependencies preserve the original source; none is copied or modified.

Generation runs with read-only sandbox, no approvals, process-local disabling of shell, app, web, hooks, memory and multi-agent features. Inherited MCP servers cause a stop if the empty-server override did not clear them. The model is instructed to treat supplied content as data and perform no actions. Existing Codex auth/config remain Codex-managed; the application does not read token files or rewrite user settings. These controls are a local MVP boundary, not a general defense against every malicious document or host configuration.

## Memory and state

| Category | Lifetime / persistence | Purpose in this MVP |
| --- | --- | --- |
| Conversation History | In-memory complete question/answer pairs, maximum 3 exchanges and 6000 combined text characters; cleared on process exit | Carries recent conversational context for repeated library calls. CLI asks one question per process. Old exchanges are evicted; an oversized exchange is dropped entirely. |
| Short-term Memory | Current call only; question, retrieved chunks and MCP response are temporary local values | Supplies evidence to synthesis without treating it as a lasting memory. |
| Long-term Memory | Existing Week 11 PostgreSQL documents/chunks are durable and managed outside Week 12 | Provides curated knowledge. This MVP performs no long-term-memory writes. |
| RAG | Existing corpus persists; query vectors and selected hits last one call | Retrieves relevant evidence at answer time; it is not an accumulating conversation log. |
| Agent State | In-memory source results, current prompt and App Server turn IDs; no durable checkpoints | Coordinates retrieval, MCP and generation, then discards per-turn execution state. |

Each synthesis uses a **fresh ephemeral App Server thread** instead of resuming an unbounded remote conversation. Application history is bounded before transmission. Question text is limited to 2000 characters; retrieval to five chunks, each with at most 2000 content / 1000 source-path / 500 heading characters; MCP JSON to 12000 characters; model answers to 16000 characters. Those are character budgets, not token guarantees. Long source fields are clipped for the prompt and provenance. A failed call is not added to history. There are no LangGraph checkpoints, whole-vault scans, automatic indexing or real-device operations. Codex owns its authentication/runtime files; ephemeral threads and disabled history are not a promise about service-side retention.

## Offline validation

```powershell
uv sync --dev
uv run pytest
uv run python -m homelab_knowledge_agent --help
```

Tests inject fake RAG, MCP sessions and generation responses. They check both evidence sources reach synthesis, provenance and mock disclosure, bounded history, explicit read-only retrieval, mock subprocess environment, JSONL notification interleaving, final-turn status and redacted errors. Automatic guards reject database connections, subprocess launches and network connects during pytest. Tests require no database, credentials, real devices, model service or billing. Dependency installation via uv may need package-network access.

The authenticated command is a separate manual smoke, never part of pytest. Do not label an auth-status pass, an empty retrieval, or fake-generation tests as an authenticated combined-answer pass. Missing DB/auth configuration must be reported as a blocker, with earlier offline work preserved.
