# Week 14 — Persistence and Checkpoint

A deterministic, offline LangGraph exercise for process-crash recovery. Three sequential graph nodes print `Step1`, `Step2`, and `Step3`. Step3 records a mock notification in SQLite, then the demo can terminate the process before returning its graph update.

## Run

From this directory, with Python 3.12+ and uv:

```powershell
uv sync --dev
uv run pytest
uv run persistence-checkpoint-lab start --crash-step3
uv run persistence-checkpoint-lab inspect
uv run persistence-checkpoint-lab resume
uv run persistence-checkpoint-lab inspect
```

Run `resume` once more to confirm that a completed thread does no work. Use a fresh
database or thread ID for each crash demonstration: the simulated crash fires only
when Step3 first inserts its durable effect key. Unknown-thread inspection and resume
exit with status 2. The CLI disables LangSmith tracing even if it is enabled in the
shell environment.

The default thread ID is `week14-demo`; the SQLite database is `data/week14.sqlite`. The `--db` and `--thread-id` global options select another local database or thread. The module entry point `uv run python -m persistence_checkpoint_lab.cli` works too. Runtime uses local graph code and SQLite only; no model, API key, network service, or LangSmith tracing is needed. Dependency installation may access the package index.

Expected recovery trace:

```text
Step1 ✓
Step2 ✓
Step3 side effect: created (week14-demo:step3:mock-notification)
Step3 crash before graph update (exit 86)
```

The first command exits with status 86 after the mock effect commits. A fresh process running `inspect` sees `completed_steps` as `Step1, Step2`, `next` as `step3`, and one recorded effect. `resume` runs Step3 again, observes the existing effect key, returns the graph update, and completes the thread. It does not run Steps 1 or 2. A second resume reports that the thread is complete and does not execute any node. A missing thread is reported as unknown by `inspect` and `resume`.

## Persistence and side effects

The graph uses the file-backed `SqliteSaver` and a stable thread ID. Invocations use `durability="sync"`, so each completed super-step's checkpoint is synchronously persisted before the graph proceeds to the next super-step. In this sequential graph, Step1 and Step2 are separate super-steps; the Step2 checkpoint records Step3 as next. Checkpoints happen at graph super-step boundaries, rather than at every line inside a node. An unfinished node can run again after restart because its update was not returned and checkpointed before the crash.

Step3 demonstrates why checkpointing alone does not provide exactly-once external effects. The mock effect and its unique idempotency key are committed before the simulated crash, while Step3's graph update is lost. On resume Step3 executes again; `INSERT OR IGNORE` with the durable key `<thread_id>:step3:mock-notification` ensures the mock effect is recorded exactly once. A real external service needs its own idempotency support or a durable outbox/reconciliation design; checkpointing by itself cannot atomically commit an unrelated external action and graph state.

Both the checkpoint connection and the mock effect transaction use SQLite `synchronous=FULL`. The mock effect table shares the local database file with the checkpointer but is committed as its own transaction.

## Graph

```mermaid
flowchart LR
    START --> Step1 --> Step2 --> Step3 --> END
```

The relevant recovery state after the crash is `completed_steps=[Step1, Step2]` with `next=[step3]`. LangGraph resumes from the persisted thread state when invoked with `None` and the same `thread_id`.

## Reference

Checkpoint and durability behavior follows the [LangGraph checkpointer guide](https://docs.langchain.com/oss/python/langgraph/checkpointers). SQLite checkpointer APIs are provided by the separately installed `langgraph-checkpoint-sqlite` package.
