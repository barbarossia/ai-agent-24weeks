# Security model

## Scope

The lab diagnoses a fixed synthetic Netflix incident. It does not connect to a home network, DNS resolver, proxy, node, rule store, log service, external MCP endpoint, or remote model. Runtime MCP clients start only the bundled Python simulator processes over stdio. Compose disables runtime networking.

## Boundaries and controls

| Boundary | Data or capability | Control |
|---|---|---|
| Request intake | Operator text | Maximum 500 characters; only Netflix and the fixture domains are accepted; the raw text is reduced to a canonical summary before it enters graph state. |
| Knowledge retrieval | Bundled Obsidian-style Markdown | Lexical retrieval is limited to Markdown under `vault/knowledge/`; resolved paths must stay in that folder; instruction-like paragraphs are dropped; claims in diagnosis/report cite the retrieved source and line. |
| Diagnostic MCP | DNS, proxy, node, route, and log observations | Separate read-only server with exactly five tools, fixed arguments, fixed scenarios, and bounded log count. It cannot write or inspect host resources. |
| Log content | Synthetic event records | Only structured fixture fields and fixed event codes inform diagnosis; instruction-like messages are redacted before graph state/checkpointing. |
| Approval | Proposed simulated action | LangGraph interrupts and checkpoints before the writer process starts. Approval must match the allowlisted action ID and proposal SHA-256 digest. Missing, rejected, or forged approval cannot reach the writer. |
| Simulated remediation MCP | One in-memory overlay action | A separate server exposes exactly one allowlisted tool and requires a short-lived one-run capability minted only after approval. It mutates no file or service. The capability is not checkpointed, traced, or printed. |
| Report export | Generated Markdown report | Optional export requires a separate `SAVE` confirmation, fixed generated filename, path validation, and a destination under `vault/knowledge/reports/`, which the retriever indexes on subsequent runs. |
| Container | Python app and local data | Runs as UID 65532 with a read-only root, no network, dropped capabilities, and `no-new-privileges`. `/data` stores checkpoints/run artifacts; a separate named volume holds confirmed report exports under the knowledge folder. |

## Approval behavior

The ordinary demo pauses for an explicit `approve` or `reject` answer. An EOF or any other response leaves the checkpoint pending and makes no write-tool call. `resume` requires an explicit decision and approver label. `--decision approve` is also an explicit command-line approval. Golden recovery evals carry synthetic approval inputs solely to make the three local demos deterministic; separate pause and rejection evals check that no write occurs without approval. None can authorize an action outside the simulator.

The write server is not started while a demo is paused or rejected. It is created only in the post-approval graph node. The read and simulated-write servers are separate processes with distinct tool inventories.

## Prompt-injection handling

User requests are never treated as tool instructions. Retrieved Markdown and logs are untrusted evidence. A small deterministic pattern filter removes known instruction-like paragraphs/messages, while the agents consume typed fields, fixed log codes, source citations, and a fixed action allowlist. No retrieved or user-provided content is executed or passed into shell commands.

This is a bounded teaching simulator, not a security claim for a production agent or a live homelab integration.
