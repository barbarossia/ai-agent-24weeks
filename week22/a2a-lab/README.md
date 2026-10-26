# Week 22 — A2A Interoperability Lab

This standalone lab demonstrates two independent Agent Services collaborating over the released A2A 1.0 protocol. Both services run as separate local processes and exchange SDK messages over loopback HTTP. The agents and all data are deterministic fakes.

## MCP and A2A

MCP standardizes how an agent connects to tools, APIs, and data resources and exchanges structured inputs and outputs. A2A standardizes how independent agents discover one another, communicate as peers, manage tasks, and exchange results. An agent can use A2A to delegate work to another agent, while either agent can use MCP for its own tools. The protocols cover different boundaries and can work together. See the official [A2A and MCP comparison](https://a2a-protocol.org/v1.0.1/topics/a2a-and-mcp/) and the [A2A core concepts](https://a2a-protocol.org/v1.0.1/topics/key-concepts/).

## Run

From this directory, install the pinned dependency graph and run the checks:

```sh
uv sync --locked --extra test
uv run pytest -q
uv run week22-a2a-demo
```

The demo starts the specialist and coordinator as separate subprocesses, resolves both Agent Cards through the SDK, and sends one streamed A2A task to the coordinator. The coordinator discovers the specialist's card and sends it a second A2A message. The printed JSON contains both task states, message IDs and states, the delegated artifact, and the correlated trace.

SDK-generated task and message IDs vary between runs. Agent behavior, synthetic data, status transitions, and trace event order are deterministic.

## What the lab shows

- **Discovery:** Both services publish `/.well-known/agent-card.json`. Their `AgentInterface.protocol_version` is `1.0`, and the coordinator uses the SDK `A2ACardResolver` before creating an A2A client.
- **Cross-agent flow:** The coordinator sends a user-role message to the specialist using A2A JSON-RPC. The specialist returns a `specialist-result` artifact and task updates; the coordinator includes the delegated result in its own `coordination-result` artifact.
- **Trace and state:** The coordinator carries a trace ID in A2A request metadata and propagates it to the specialist. Task, status, and artifact metadata carry span IDs and parent spans. The final artifact records message IDs and states, both task IDs and status transitions, and the ordered trace.
- **Failure:** `remote_failure` makes the specialist return an A2A task in the `failed` state. The coordinator returns a failed task with the synthetic error.
- **Timeout:** `slow` delays the fake specialist by 300 ms. The coordinator bounds its remote call to 150 ms and returns a failed task with `remote_timeout`. The remote service may finish its task after the coordinator stops waiting; the coordinator's result records the state it observed at timeout.

The tests exercise card discovery, cross-service message/task/artifact flow, correlated trace IDs, task state transitions, remote task failure, and the bounded timeout.

## Protocol and SDK sources

The project uses the official [A2A Protocol Specification 1.0.1](https://a2a-protocol.org/v1.0.1/specification/) with `protocol_version="1.0"` on each Agent Interface. The [official Python quickstart](https://a2a-protocol.org/v1.0.1/tutorials/python/) documents the Agent Card, `AgentExecutor`, task updates, server routes, and SDK client pattern used here.

The dependency pins the official [`a2a-sdk` 1.2.3 release](https://pypi.org/project/a2a-sdk/1.2.3/). Its compatibility table lists A2A 1.0 support for JSON-RPC clients and servers. The SDK source is maintained in the [official A2A Python repository](https://github.com/a2aproject/a2a-python). The complete resolved dependency graph is committed in `uv.lock`.

## Scope limits

The coordinator and specialist use fixed synthetic logic and sample data only. Service URLs are restricted to HTTP on `127.0.0.1`; no external network, model API, credentials, MCP server, or real homelab access is used by the demo. Task storage is in-memory. This lab makes no production authentication, authorization, durability, high availability, or scale claims.
