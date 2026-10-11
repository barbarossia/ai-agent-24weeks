# Week 20 — Auth / Permission / Sandbox Lab

An offline, standard-library demonstration of a fail-closed tool boundary. It
connects authenticated identity, RBAC, exact human approval, an in-memory
sandbox, evaluation, trace events, bounded metrics, and metadata-only audit.
It makes no network calls and runs no shell commands.

## Run

```sh
cd week20/permission-sandbox-lab
python3 -m src.week20_permission_sandbox
PYTHONPATH=src python3 -m pytest -q
```

The demo prints six deterministic permission scenarios and summarizes the
corresponding audit records, trace events, and metric series. It uses only
synthetic identities and state.

## Permission contract

| Tool | Minimum role | Human approval |
| --- | --- | --- |
| `get_esxi_status` | `READ_ONLY` | No |
| `restart_container` | `OPERATOR` | No |
| `restart_host` | `ADMIN` | Yes |

The role is carried by an immutable `Principal` created from claims that a
trusted OIDC library has already validated. `AuthAdapter` checks issuer,
audience, subject, and the allow-listed role name; it does **not** verify JWT
signatures or replace an OAuth2/OIDC provider. The model's requested role is
untrusted data and cannot alter the principal or authorization decision.

Approval is bound to the authenticated subject, tool, and canonical request
digest, and requires a distinct human approver. A changed request or
self-approval fails closed. In production, this approval record must be
cryptographically protected, short-lived, and issued by a separately
authenticated approval service.

## Sandbox, secrets, and evidence

Tool handlers only touch the boundary's in-memory fake homelab state. No
credentials are stored or read by the lab. The `.gitignore` excludes `.env`,
secret directories, and private-key files; never commit real credentials.
The sandbox here is a deterministic capability boundary, not an OS/container
isolation claim. Production tools still need process/container isolation,
network egress controls, and a managed secret provider.

Each call emits a permission decision, a paired trace event, a bounded
`(tool, outcome)` metric, and an audit row. Audit and trace data intentionally
exclude arguments and secret values. The integrated six-scenario eval checks
read access, role denial, attempted role escalation, operator execution,
approved high-risk action, and missing approval. This demonstrates the
Week 17 eval + Week 18 trace/metrics + Week 19 policy boundary + Week 15 HITL +
audit loop using a single offline execution path; it is not a production
telemetry or durable audit backend.
