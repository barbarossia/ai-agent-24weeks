from week20_permission_sandbox.core import (
    AgentBoundary, Approval, AuthAdapter, AuthError, Principal, Role, demo, request_digest,
)


def test_oidc_claim_mapping_checks_issuer_audience_and_role():
    auth = AuthAdapter(issuer="https://issuer.example.test", audience="homelab-agent")
    principal = auth.principal_from_validated_claims({
        "iss": "https://issuer.example.test", "aud": ["homelab-agent"],
        "sub": "alice", "role": "READ_ONLY",
    })
    assert principal == Principal("alice", Role.READ_ONLY)
    for claims in (
        {"iss": "wrong", "aud": "homelab-agent", "sub": "alice", "role": "ADMIN"},
        {"iss": "https://issuer.example.test", "aud": "wrong", "sub": "alice", "role": "ADMIN"},
        {"iss": "https://issuer.example.test", "aud": "homelab-agent", "sub": "alice", "role": "ROOT"},
    ):
        try:
            auth.principal_from_validated_claims(claims)
        except AuthError:
            pass
        else:
            raise AssertionError("invalid identity claims must fail closed")


def test_tool_roles_and_agent_role_escalation():
    boundary = AgentBoundary(Principal("alice", Role.READ_ONLY))
    assert boundary.tools["get_esxi_status"].required_role is Role.READ_ONLY
    assert boundary.tools["restart_container"].required_role is Role.OPERATOR
    assert boundary.tools["restart_host"].required_role is Role.ADMIN
    denied = boundary.call("restart_container", {"name": "demo-container"}, requested_role="ADMIN")
    assert denied["reason"] == "insufficient_permission"
    assert boundary.state["container"] == "running"


def test_agent_cannot_self_approve_or_replay_approval_for_changed_request():
    args = {}
    own_approval = Approval("alice", "restart_host", request_digest("restart_host", args), True, "alice")
    boundary = AgentBoundary(Principal("alice", Role.ADMIN), approval=own_approval)
    assert boundary.call("restart_host", args)["reason"] == "approval_required"
    approval = Approval("alice", "restart_host", request_digest("restart_host", args), True, "reviewer")
    boundary = AgentBoundary(Principal("alice", Role.ADMIN), approval=approval)
    assert boundary.call("restart_host", {"other": "request"})["reason"] == "approval_required"


def test_full_eval_closes_permission_trace_metrics_and_audit_loop():
    passed, audit, events, metrics = demo()
    assert passed
    assert len(audit) == 6
    assert len(events) == 12
    assert sum(metrics.values()) == 6


def test_audit_trace_and_metrics_do_not_record_arguments():
    boundary = AgentBoundary(Principal("alice", Role.READ_ONLY))
    boundary.call("get_esxi_status", {})
    serialized = repr((boundary.audit.records, boundary.events, boundary.metrics.calls))
    assert "secret" not in serialized.lower()
    assert "arguments" not in serialized.lower()
