"""A deterministic, fail-closed tool boundary for the Week 20 lab.

This module deliberately has no network, shell, filesystem, or model access.
The demo tools operate on an in-memory fake homelab only.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from hashlib import sha256
import json
from typing import Callable, Mapping


class Role(IntEnum):
    READ_ONLY = 1
    OPERATOR = 2
    ADMIN = 3


@dataclass(frozen=True)
class Principal:
    """Identity established by a trusted auth adapter, never by the agent."""

    subject: str
    role: Role


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required_role: Role
    human_approval: bool
    handler: Callable[[Mapping[str, object]], object]


@dataclass(frozen=True)
class Approval:
    subject: str
    tool: str
    request_digest: str
    approved: bool
    approver: str


@dataclass(frozen=True)
class Event:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    attributes: Mapping[str, str]


class AuthError(ValueError):
    pass


class AuthAdapter:
    """Maps already-validated OIDC claims into a local principal.

    Signature, issuer, audience, expiry, and nonce validation belong to the
    OIDC provider/library before this adapter is called. Unknown roles fail closed.
    """

    def __init__(self, *, issuer: str, audience: str, role_claim: str = "role"):
        self.issuer = issuer
        self.audience = audience
        self.role_claim = role_claim

    def principal_from_validated_claims(self, claims: Mapping[str, object]) -> Principal:
        if claims.get("iss") != self.issuer:
            raise AuthError("issuer_mismatch")
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if self.audience not in audiences:
            raise AuthError("audience_mismatch")
        subject = claims.get("sub")
        role_text = claims.get(self.role_claim)
        if not isinstance(subject, str) or not subject or len(subject) > 128:
            raise AuthError("invalid_subject")
        try:
            role = Role[str(role_text)]
        except (KeyError, TypeError):
            raise AuthError("unknown_role") from None
        return Principal(subject=subject, role=role)


class AuditLog:
    """In-memory audit sink containing metadata only, never tool arguments."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append(self, *, subject: str, tool: str, decision: str, reason: str,
               role: Role, approval_subject: str | None = None) -> None:
        self.records.append({
            "subject": subject,
            "tool": tool,
            "role": role.name,
            "decision": decision,
            "reason": reason,
            "approval_subject": approval_subject,
        })


class Metrics:
    def __init__(self) -> None:
        self.calls: dict[tuple[str, str], int] = {}

    def record(self, tool: str, outcome: str) -> None:
        key = (tool, outcome)
        self.calls[key] = self.calls.get(key, 0) + 1


class AgentBoundary:
    """Executes only registered tools under the authenticated principal."""

    def __init__(self, principal: Principal, *, approval: Approval | None = None):
        self._principal = principal
        self._approval = approval
        self.audit = AuditLog()
        self.metrics = Metrics()
        self.events: list[Event] = []
        self._next_id = 0
        self.state = {"container": "running", "host": "online"}
        self.tools = {
            "get_esxi_status": ToolSpec("get_esxi_status", Role.READ_ONLY, False,
                                         self._get_esxi_status),
            "restart_container": ToolSpec("restart_container", Role.OPERATOR, False,
                                           self._restart_container),
            "restart_host": ToolSpec("restart_host", Role.ADMIN, True,
                                     self._restart_host),
        }

    @staticmethod
    def _get_esxi_status(args: Mapping[str, object]) -> object:
        if args:
            raise ValueError("invalid_arguments")
        return {"status": "online"}

    def _restart_container(self, args: Mapping[str, object]) -> object:
        if set(args) != {"name"} or args.get("name") != "demo-container":
            raise ValueError("invalid_arguments")
        self.state["container"] = "running"
        return {"status": "restarted"}

    def _restart_host(self, args: Mapping[str, object]) -> object:
        if args:
            raise ValueError("invalid_arguments")
        self.state["host"] = "online"
        return {"status": "restarted"}

    @staticmethod
    def _digest(tool: str, args: Mapping[str, object]) -> str:
        canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode()).hexdigest()

    def call(self, tool: str, args: Mapping[str, object], *, requested_role: str | None = None) -> dict[str, object]:
        """Run a tool; requested_role is untrusted agent data and never grants access."""
        self._next_id += 1
        trace_id = "trace-20-demo"
        span_id = f"span-{self._next_id}"
        parent_span_id = "span-request"
        self.events.append(Event("permission.check", trace_id, span_id, parent_span_id,
                                 {"tool": tool if tool in self.tools else "unknown", "stage": "permission"}))
        spec = self.tools.get(tool)
        outcome = "denied"
        reason = "unknown_tool"
        result: object = None
        approval_subject = None
        if spec:
            # Agent-controlled role strings are deliberately excluded from this calculation.
            if self._principal.role < spec.required_role:
                reason = "insufficient_permission"
            elif requested_role is not None and requested_role != self._principal.role.name:
                reason = "role_escalation_ignored"
            elif spec.human_approval and not self._valid_approval(tool, args):
                reason = "approval_required"
            else:
                try:
                    result = spec.handler(args)
                except (ValueError, TypeError) as exc:
                    reason = str(exc) if str(exc) == "invalid_arguments" else "invalid_arguments"
                else:
                    outcome = "allowed"
                    reason = "approved" if spec.human_approval else "allowed"
                    approval_subject = self._approval.approver if spec.human_approval and self._approval else None
        decision = "allow" if outcome == "allowed" else "deny"
        self.audit.append(subject=self._principal.subject, tool=tool if spec else "unknown",
                          decision=decision, reason=reason, role=self._principal.role,
                          approval_subject=approval_subject)
        self.metrics.record(tool if spec else "unknown", outcome)
        self.events.append(Event("tool.execute" if outcome == "allowed" else "tool.denied",
                                 trace_id, f"span-{self._next_id}-result", span_id,
                                 {"tool": tool if spec else "unknown", "outcome": outcome}))
        return {"allowed": outcome == "allowed", "reason": reason, "result": result,
                "trace_id": trace_id}

    def _valid_approval(self, tool: str, args: Mapping[str, object]) -> bool:
        approval = self._approval
        if not approval or not approval.approved:
            return False
        if not approval.approver or approval.approver == self._principal.subject:
            return False
        if approval.subject != self._principal.subject or approval.tool != tool:
            return False
        if approval.request_digest != self._digest(tool, args):
            return False
        return True


def request_digest(tool: str, args: Mapping[str, object]) -> str:
    """Build the exact approval binding for a human approval adapter/test."""
    return AgentBoundary._digest(tool, args)


def demo() -> tuple[bool, list[dict[str, object]], list[Event], dict[tuple[str, str], int]]:
    reader = AgentBoundary(Principal("alice", Role.READ_ONLY))
    operator = AgentBoundary(Principal("bob", Role.OPERATOR))
    admin_args: dict[str, object] = {}
    admin = AgentBoundary(Principal("carol", Role.ADMIN), approval=Approval(
        subject="carol", tool="restart_host", request_digest=request_digest("restart_host", admin_args),
        approved=True, approver="human-reviewer"))
    scenarios = [
        (reader, "get_esxi_status", {}, None, True, "allowed"),
        (reader, "restart_container", {"name": "demo-container"}, None, False, "insufficient_permission"),
        (operator, "restart_container", {"name": "demo-container"}, "ADMIN", False, "role_escalation_ignored"),
        (operator, "restart_container", {"name": "demo-container"}, None, True, "allowed"),
        (admin, "restart_host", admin_args, None, True, "approved"),
        (AgentBoundary(Principal("dave", Role.ADMIN)), "restart_host", admin_args, None, False, "approval_required"),
    ]
    passed = True
    events: list[Event] = []
    metrics: dict[tuple[str, str], int] = {}
    audit: list[dict[str, object]] = []
    for boundary, tool, args, role, expected_allowed, expected_reason in scenarios:
        result = boundary.call(tool, args, requested_role=role)
        passed &= result["allowed"] is expected_allowed and result["reason"] == expected_reason
        audit.append(boundary.audit.records[-1])
        events.extend(boundary.events[-2:])
        metric_key = (tool if tool in boundary.tools else "unknown",
                      "allowed" if result["allowed"] else "denied")
        metrics[metric_key] = metrics.get(metric_key, 0) + 1
    passed &= len(audit) == len(scenarios) and len(events) == len(scenarios) * 2
    return passed, audit, events, metrics


def main() -> int:
    passed, audit, events, metrics = demo()
    print(f"eval={'PASS' if passed else 'FAIL'} scenarios=6")
    print(f"trace_events={len(events)} audit_records={len(audit)} metric_series={len(metrics)}")
    for record in audit:
        print(f"audit {record['decision']} tool={record['tool']} role={record['role']} reason={record['reason']}")
    for (tool, outcome), count in sorted(metrics.items()):
        print(f"metric tool={tool} outcome={outcome} count={count}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
