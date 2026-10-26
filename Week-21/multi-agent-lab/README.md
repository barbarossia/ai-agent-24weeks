# Week 21 — Supervisor / Worker Multi-Agent Lab

A deterministic, offline Python demonstration of a Supervisor coordinating
Network, ESXi, Docker, and Knowledge specialists. It uses only fixed in-memory
fixtures and the Python standard library. It makes no network calls, starts no
containers or hosts, reads no credentials, and calls no model provider.

## Run

From the repository root:

```sh
cd Week-21/multi-agent-lab
PYTHONPATH=src python3 -m week21_multi_agent_lab
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The demo prints the routed workers, their evidence and tool scopes, the
Network-to-Docker handoff, the final diagnosis with source evidence IDs, and a
six-dimension comparison. Repeated runs produce the same output.

## Architecture

`Supervisor.route()` deterministically maps explicit network/DNS, ESXi,
Docker/container, and knowledge/runbook terms to one specialist. An outage
request routes Network and Docker tasks together through a thread pool, even
when its text also contains a DNS or Docker specialist keyword. Explicit
runbook requests route to Knowledge, and ESXi host outages route to ESXi. Each
worker returns a `SpecialistReport` containing typed `Evidence` records. Every
record carries `Provenance` with its producing agent, tool, request ID, and,
for derived results, source evidence IDs.

For the synthetic API outage, Network reports that `api.lab.test` resolves to
`10.0.0.42` and that the route is reachable. Docker independently reports a
healthy `api` container listening at `10.0.0.24:8080`. Network's evidence is
passed in a typed `HandoffMessage` to Docker. Docker validates the referenced
Network evidence, correlates it with its own report, and returns a diagnosis
whose provenance cites both workers' evidence. The supervisor then presents
the stale DNS record as the cause.

ESXi and Knowledge are independently routable workers too: ESXi reports
synthetic host and datastore state, and Knowledge returns a static DNS
runbook recommendation. They are not needed to diagnose this particular
outage.

## Permission matrix

Every specialist owns a distinct immutable `ToolCapability`. The capability
checks its allowlist before dispatching a request to the shared in-memory
fixture toolbox; a denied tool call raises `PermissionDenied` before tool
execution. The supervisor has no diagnostic tools.

| Specialist | Allowed read tools |
| --- | --- |
| Network | `dns_lookup`, `route_status` |
| ESXi | `esxi_host_status`, `datastore_status` |
| Docker | `container_status`, `container_log_summary` |
| Knowledge | `runbook_search` |

There are no write tools. These are application-level capability checks in
one Python process, not security sandboxes.

## Comparison assumptions

The baseline is one agent with the union of the same read tools, using a
sequential control loop. Both designs use the same task and fixture data.
Isolation below describes code organization; it does not claim OS isolation.
The multi-agent outage run submits the two independent checks before the
handoff, but the local fixture reads are tiny, so the demo does not claim a
latency improvement.

| Dimension | Supervisor / Worker | Single agent plus tools | Assumption |
| --- | --- | --- | --- |
| Isolation | Separate worker instances and evidence; logical separation only | One process and one agent state | Neither design is an OS/container sandbox here |
| Context | Focused worker tasks; supervisor receives typed summaries and cited evidence | One agent accumulates all tool results | Prompt organization only; token counts are not measured |
| Permissions | Independent per-specialist allowlists enforced on each call | Agent receives the union of required tools | Both are read-only in this fixture |
| Parallelism | Network and Docker checks fan out before correlation | Assumed sequential tool loop | Structure is demonstrated; speedup is not measured |
| Complexity | Routing, worker contracts, handoff validation, provenance, synthesis | One control loop and direct tool handling | Same task and evidence sources |
| Cost | `$0.00` synthetic spend; supervisor plus two workers; four fixture reads | `$0.00` synthetic spend; one agent; the same four reads | No model/provider is called. Production token and dollar costs are not measured; worker and handoff prompts usually add overhead |

The displayed `$0.00` is the actual external spend of this offline run, not a
prediction of production cost. A model-backed version would pay for supervisor
and worker prompts/responses, including handoff context; the single-agent
baseline would usually need fewer model turns. Exact costs depend on the
chosen models, prompt sizes, retries, and tool services, none of which are
configured here.

## Limitations

- The router is keyword-based and deterministic; it does not interpret open
  ended language or use an LLM.
- Thread-pool fan-out demonstrates orchestration shape only. It does not model
  remote worker latency, failures, retries, cancellation, or measured speedup.
- All agents and capabilities live in one process. A Python object boundary is
  not a hostile-code security boundary.
- Fixtures contain one service outage, one ESXi host, and one static runbook;
  there is no real DNS, network, Docker, ESXi, filesystem, or provider access.
- Cost comparison is qualitative except for the demo's exact zero external
  spend and fixture tool-read count. No token or dollar estimate is claimed.
