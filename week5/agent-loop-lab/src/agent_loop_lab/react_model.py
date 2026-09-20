"""A deterministic mock "model" that decides the agent's next step.

This is the "brain" side of the hand-written Agent Loop. On every call it
receives the original question plus everything observed *so far* (the
``Observation`` history) and returns a ``Decision``:

- an **action** (``action`` + ``action_input``) — "call this tool with these
  arguments, then come back and ask me again with the result appended to
  history", or
- a **final answer** (``final_answer``) — "stop, here is the answer for the
  user".

Real LLM-backed agents make exactly this choice at every ReAct step
(Thought -> Action -> Observation -> ... -> Final Answer). This mock
reproduces the same decision shape with simple, deterministic rules — no
randomness, no network, no API key — so the surrounding loop (agent_loop.py)
can be exercised and tested without a real model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

_HOST_TOKEN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_-]*\d[a-zA-Z0-9_-]*\b")
_DOMAIN_TOKEN = re.compile(r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}\b")


@dataclass
class Observation:
    """What the loop learned from executing one action."""

    action: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class Decision:
    """The model's choice for the current step.

    Exactly one of ``action`` or ``final_answer`` should be set; the loop
    treats an action-less, answer-less decision as an implicit (empty) final
    answer so a buggy model can never crash the loop.
    """

    thought: str
    action: Optional[str] = None
    action_input: Optional[dict[str, Any]] = None
    final_answer: Optional[str] = None


def _find_observation(history: list[Observation], action: str) -> Optional[Observation]:
    for observation in history:
        if observation.action == action:
            return observation
    return None


@dataclass
class ReactModel:
    """Deterministic ReAct-style decision maker.

    Two behaviors, chosen by keyword:

    - ``"diagnose <host>"`` / ``"troubleshoot <host>"``: a genuine multi-step
      chain — check host status, then (if the host is up) docker status,
      then active alerts — stopping *early* the moment the host is found to
      be down (no point checking docker/alerts on a dead host).
    - anything else: at most one tool call (status / docker / dns), mirroring
      Week 4's single-round behavior, then a final answer.
    """

    call_log: list[str] = field(default_factory=list)

    def decide(self, question: str, history: list[Observation]) -> Decision:
        self.call_log.append(f"decide: question={question!r} history_len={len(history)}")
        question_lower = question.lower()
        host_match = _HOST_TOKEN.search(question)
        domain_match = _DOMAIN_TOKEN.search(question)

        if ("diagnose" in question_lower or "troubleshoot" in question_lower) and host_match:
            return self._diagnose_step(host_match.group(0), history)

        if history:
            # Week-4-style single-tool question: one action, then summarize.
            last = history[-1]
            return Decision(
                thought="tool result received, producing final answer",
                final_answer=_summarize_single(last),
            )

        if "docker" in question_lower and host_match:
            return Decision(
                thought="question is about docker containers",
                action="get_docker_status",
                action_input={"host": host_match.group(0)},
            )
        if ("dns" in question_lower or "resolve" in question_lower or domain_match) and domain_match:
            return Decision(
                thought="question is about DNS resolution",
                action="get_dns_result",
                action_input={"domain": domain_match.group(0)},
            )
        if ("status" in question_lower or "host" in question_lower or "up" in question_lower) and host_match:
            return Decision(
                thought="question is about host status",
                action="get_host_status",
                action_input={"host": host_match.group(0)},
            )

        return Decision(
            thought="no matching tool for this question",
            final_answer=(
                "I don't have a tool for that question. Try asking me to "
                "diagnose a host, or about a host's status, docker "
                "containers, or DNS resolution."
            ),
        )

    def _diagnose_step(self, host: str, history: list[Observation]) -> Decision:
        host_obs = _find_observation(history, "get_host_status")
        if host_obs is None:
            return Decision(
                thought=f"start diagnosis: check host status for {host!r}",
                action="get_host_status",
                action_input={"host": host},
            )

        if host_obs.error is not None:
            return Decision(
                thought="host status check itself failed; stop diagnosis early",
                final_answer=(
                    f"Diagnosis for '{host}': could not read host status "
                    f"({host_obs.error}). Stopping here — escalate to a human."
                ),
            )

        if host_obs.result is not None and host_obs.result.get("status") == "down":
            return Decision(
                thought="host is down; skip docker/alert checks and stop early",
                final_answer=(
                    f"Diagnosis for '{host}': host is DOWN. Skipping docker/alert "
                    "checks since the host itself is unreachable — escalate immediately."
                ),
            )

        docker_obs = _find_observation(history, "get_docker_status")
        if docker_obs is None:
            return Decision(
                thought=f"host is up, next check docker containers for {host!r}",
                action="get_docker_status",
                action_input={"host": host},
            )

        alert_obs = _find_observation(history, "check_alerting")
        if alert_obs is None:
            return Decision(
                thought=f"docker checked, next check active alerts for {host!r}",
                action="check_alerting",
                action_input={"host": host},
            )

        return Decision(
            thought="all checks complete, producing final diagnosis",
            final_answer=_summarize_diagnosis(host, host_obs, docker_obs, alert_obs),
        )


class StubbornModel(ReactModel):
    """A model that never produces a final answer for diagnosis questions.

    It always re-issues ``get_host_status`` no matter what history already
    contains. This exists purely to demonstrate (in the CLI demo and in
    tests) that the surrounding loop's ``max_steps`` guard is what stops an
    agent from looping forever — the model itself will never volunteer to
    stop.
    """

    def decide(self, question: str, history: list[Observation]) -> Decision:
        host_match = _HOST_TOKEN.search(question)
        host = host_match.group(0) if host_match else "web01"
        return Decision(
            thought="(stubborn) always re-checking host status, never satisfied",
            action="get_host_status",
            action_input={"host": host},
        )


def _summarize_single(observation: Observation) -> str:
    if observation.error is not None:
        return f"I tried to call {observation.action} but it failed: {observation.error}"

    result = observation.result or {}
    if observation.action == "get_host_status":
        return (
            f"Host '{result.get('host')}' is {result.get('status')}"
            + (f" (latency {result['latency_ms']} ms)." if result.get("latency_ms") is not None else ".")
        )
    if observation.action == "get_dns_result":
        return f"'{result.get('domain')}' resolves to {result.get('resolved_ip')} (ttl {result.get('ttl')}s)."
    if observation.action == "get_docker_status":
        names = ", ".join(f"{c['name']}={c['state']}" for c in result.get("containers", []))
        return f"Docker containers on '{result.get('host')}': {names}."
    return f"Tool {observation.action} returned: {result}"


def _summarize_diagnosis(
    host: str,
    host_obs: Observation,
    docker_obs: Observation,
    alert_obs: Observation,
) -> str:
    parts = [f"Diagnosis for '{host}':", f"host status = {host_obs.result.get('status')}."]

    if docker_obs.error is not None:
        parts.append(f"docker check failed: {docker_obs.error}.")
    else:
        containers = docker_obs.result.get("containers", []) if docker_obs.result else []
        names = ", ".join(f"{c['name']}={c['state']}" for c in containers) or "none"
        parts.append(f"docker containers: {names}.")

    if alert_obs.error is not None:
        parts.append(f"alert check failed unexpectedly: {alert_obs.error}.")
    else:
        alerts = alert_obs.result.get("alerts", []) if alert_obs.result else []
        if alerts:
            summary = "; ".join(f"{a['level']}: {a['message']}" for a in alerts)
            parts.append(f"active alerts: {summary}.")
        else:
            parts.append("no active alerts.")

    return " ".join(parts)


__all__ = [
    "ReactModel",
    "StubbornModel",
    "Decision",
    "Observation",
]
