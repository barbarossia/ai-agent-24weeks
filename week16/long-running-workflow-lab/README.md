# Week 16 — Persistent long-running workflow lab

This offline lab implements `Diagnose → parallel DNS/service/connectivity/logs checks → join → Analyze → Proposed Fix → Human Approval` with LangGraph and a file-backed SQLite checkpoint saver. Each branch writes its own outcome channel. Failures are retained and analysis uses every outcome that completed.

## Run it

From this directory, use the locked project environment and invoke the module:

```sh
uv sync --locked
uv run python -m long_running_workflow_lab.cli --db data/week16.sqlite --thread-id demo start --host lab.example
uv run python -m long_running_workflow_lab.cli --db data/week16.sqlite --thread-id demo inspect
uv run python -m long_running_workflow_lab.cli --db data/week16.sqlite --thread-id demo approve
```

Every command opens a fresh SQLite connection. `inspect`, `approve`, and `reject` therefore demonstrate checkpoint recovery across separate processes. `reject` ends without invoking the mock fix. The approved mock fix is idempotent per thread, recorded transactionally in SQLite, and optionally written to `W16_FIX_CALL_LOG` for demo evidence.

Commands:

```text
start [--host HOST] [--fault transient:CHECK|exhaust:CHECK|fail:CHECK]
inspect
cancel [--reason TEXT]
retry [--fault transient:CHECK|exhaust:CHECK|fail:CHECK]
approve
reject
```

`transient:CHECK` fails once then succeeds; `exhaust:CHECK` raises transient failures through the two-attempt bound; `fail:CHECK` injects a permanent check failure. The fault options are deterministic mock scenarios.

## Cancellation and recovery

Cancellation is a durable row in the same SQLite file, separate from graph state. `cancel` commits the request. The workflow checks it in `prepare`, before dispatch, and in `join`, after all dispatched checks finish. `inspect` reports the requested row separately from `cancel_observed_at` and shows all four outcomes. When cancellation arrives after fan-out dispatch, each running mock completes and checkpoints its result; cancellation does not preempt an in-flight check.

`retry` deletes the cancellation row before loading the graph. For a finished thread it derives `retry_nonce` from the saved state and invokes fresh input; for a thread with pending work it resumes with `invoke(None)`. Only missing, failed, or cancelled check channels are dispatched, and successful channels remain intact. Use one command at a time for each thread; SQLite checkpoint writes for the same thread are not designed for concurrent commands. The application-owned cancel-row update is safe while a run is active.

The crash/replay test pins this behavior for the installed LangGraph SQLite checkpointer: successful parallel check-task writes can be durable before the fan-in checkpoint commits. T7 holds one check after its mock backend returns, waits until the other three task writes are present in SQLite, then crashes the worker process. A fresh `inspect` still shows the unfinished check as next; the CLI `retry` resumes it, while durable call counters prove the three completed checks were not repeated. Conversely, `invoke(None)` on a finished thread is a no-op; CLI `retry` detects that state and supplies fresh input with the next checkpoint-derived `retry_nonce`. This replay guarantee is scoped to the tested checkpointer behavior and these read-only mock checks, not external side effects.

The retry bound is `MAX_ATTEMPTS = 2`, implemented once inside each check node. No LangGraph `RetryPolicy` is configured. The design uses cooperative polling rather than `RunControl.request_drain()`: RunControl is suited to an in-process supervisor, while this lab needs a durable request from a separate CLI process.

## Scope and limitations

- Every diagnostic and fix adapter is a local mock. The lab makes no network calls and has no real HomeLab control path.
- Cancellation is cooperative at the two graph boundaries above. It cannot interrupt a check already dispatched.
- Each check gets at most two attempts per dispatch; retries re-run only failed or cancelled checks.
- Use a stable thread ID and SQLite database path to recover state. Avoid concurrent commands against one thread.
- Approval pauses before the mock fix backend. Rejection never reaches it.
- This is a teaching lab, not a production control plane. It does not integrate Temporal, external model services, real devices, or credentials.
