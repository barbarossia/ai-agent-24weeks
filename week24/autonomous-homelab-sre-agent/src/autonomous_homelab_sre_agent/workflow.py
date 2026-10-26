from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypedDict

# Set before importing LangGraph's checkpoint serializer; persisted state contains plain data only.
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents import DiagnosticAnalyst, IndependentSREReviewer
from .knowledge import ObsidianRetriever
from .mcp_client import apply_simulated_remediation, read_diagnostics
from .models import ApprovalDecision, FixProposal
from .report import render_report
from .scenarios import FixtureScenario, get_scenario
from .security import bind_approval, understand_request
from .telemetry import TraceRecorder
from .workflow_policy import proposal_digest


class AgentState(TypedDict, total=False):
    case_id: str
    run_id: str
    request_understood: bool
    incident: dict[str, Any]
    citations: list[dict[str, Any]]
    retrieval_redactions: int
    observations: dict[str, dict[str, Any]]
    handoff: dict[str, Any]
    diagnosis: dict[str, Any]
    review: dict[str, Any]
    proposal: dict[str, Any] | None
    approval: dict[str, str]
    remediation: dict[str, str]
    verification: dict[str, dict[str, Any]]
    verification_checks: dict[str, bool]
    recovered: bool
    report: str


def initial_state(request: str, scenario: FixtureScenario, run_id: str) -> AgentState:
    assessment = understand_request(request, scenario)
    return {
        "case_id": scenario.case_id,
        "run_id": run_id,
        "incident": assessment.incident.model_dump(mode="json"),
    }


def _recovery_checks(observations: dict[str, dict[str, Any]]) -> dict[str, bool]:
    dns = observations["dns_lookup"]
    proxy = observations["proxy_health"]
    node = observations["node_health"]
    rule = observations["inspect_routing_rule"]
    logs = observations["read_recent_logs"]
    log_codes = {
        event.get("code") for event in logs.get("events", []) if isinstance(event, dict)
    }
    return {
        "dns_answer_current": dns["answers"] == dns["expected_answers"],
        "proxy_pool_healthy": proxy["healthy"] is True,
        "active_node_ready": node["status"] == node["expected_status"],
        "rule_uses_expected_route": (
            rule["action"] == rule["expected_action"] and rule["target"] == node["active_node"]
        ),
        "recovery_event_present": "SIMULATED_RECOVERY" in log_codes,
    }


def build_graph(
    *,
    checkpointer: Any,
    vault_root: Path,
    telemetry: TraceRecorder,
):
    retriever = ObsidianRetriever(vault_root)
    analyst = DiagnosticAnalyst()
    reviewer = IndependentSREReviewer()

    async def understand_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("request.understand", case_id=state["case_id"]):
            scenario = get_scenario(state["case_id"])
            if state["incident"]["case_id"] != scenario.case_id:
                raise ValueError("incident case does not match the selected fixture")
            return {"request_understood": True}

    async def retrieve_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("knowledge.retrieve", case_id=state["case_id"]):
            scenario = get_scenario(state["case_id"])
            result = retriever.retrieve(
                state["incident"]["request_summary"],
                topic_terms=scenario.topic_terms,
                top_k=3,
            )
            for _ in range(result.redacted_paragraphs):
                telemetry.increment("knowledge_redactions_total", source="obsidian")
            return {
                "citations": [item.model_dump(mode="json") for item in result.citations],
                "retrieval_redactions": result.redacted_paragraphs,
            }

    async def collect_evidence_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("diagnostics.read_only", case_id=state["case_id"]):
            observations = await read_diagnostics(
                state["case_id"], on_tool=telemetry.tool_event
            )
            return {"observations": observations}

    async def analyst_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("agent.diagnostic_analyst", case_id=state["case_id"]):
            handoff = analyst.analyze(
                case_id=state["case_id"],
                observations=state["observations"],
                citations=state.get("citations", []),
            )
            return {
                "handoff": handoff.model_dump(mode="json"),
                "diagnosis": handoff.diagnosis.model_dump(mode="json"),
            }

    async def review_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("agent.sre_reviewer", case_id=state["case_id"]):
            result = reviewer.review(state["handoff"])
            return {"review": result.model_dump(mode="json")}

    async def propose_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("remediation.propose", case_id=state["case_id"]):
            scenario = get_scenario(state["case_id"])
            if not state["review"]["accepted"]:
                return {"proposal": None}
            proposal = FixProposal(
                action_id=scenario.action_id,
                description=scenario.action_description,
                expected_effect=scenario.expected_effect,
                proposal_digest=proposal_digest(scenario),
            )
            return {"proposal": proposal.model_dump(mode="json")}

    async def approval_node(state: AgentState) -> dict[str, Any]:
        proposal = state.get("proposal")
        if not proposal:
            raise ValueError("approval requested without a proposal")
        request = {
            "kind": "simulated_remediation_approval",
            "run_id": state["run_id"],
            "case_id": state["case_id"],
            "cause": state["diagnosis"]["summary"],
            "action_id": proposal["action_id"],
            "description": proposal["description"],
            "expected_effect": proposal["expected_effect"],
            "proposal_digest": proposal["proposal_digest"],
            "message": "No simulated write runs unless a human resumes with an exact matching approval.",
        }
        # This node has no side effects before interrupt; LangGraph may restart it on resume.
        response = interrupt(request)
        decision = bind_approval(
            response,
            action_id=proposal["action_id"],
            proposal_digest=proposal["proposal_digest"],
        )
        telemetry.increment("approval_decisions_total", decision=decision["decision"])
        return {"approval": decision}

    async def execute_node(state: AgentState) -> dict[str, Any]:
        proposal = state.get("proposal")
        if not proposal:
            raise ValueError("simulated write requested without a proposal")
        approval = ApprovalDecision.model_validate(state.get("approval"))
        if approval.decision != "approve":
            raise ValueError("simulated write is not approved")
        bind_approval(
            approval.model_dump(mode="json"),
            action_id=proposal["action_id"],
            proposal_digest=proposal["proposal_digest"],
        )
        with telemetry.span(
            "simulation.apply", case_id=state["case_id"], action_id=proposal["action_id"]
        ):
            result = await apply_simulated_remediation(
                state["case_id"],
                action_id=proposal["action_id"],
                digest=proposal["proposal_digest"],
                on_tool=telemetry.tool_event,
            )
            telemetry.increment(
                "simulated_remediations_total", action_id=proposal["action_id"], outcome="ok"
            )
            return {"remediation": result}

    async def verify_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("recovery.verify", case_id=state["case_id"]):
            overlay = state["remediation"]["overlay"]
            observations = await read_diagnostics(
                state["case_id"], overlay=overlay, on_tool=telemetry.tool_event
            )
            checks = _recovery_checks(observations)
            return {
                "verification": observations,
                "verification_checks": checks,
                "recovered": all(checks.values()),
            }

    async def report_node(state: AgentState) -> dict[str, Any]:
        with telemetry.span("report.render", case_id=state["case_id"]):
            return {"report": render_report(state)}

    def route_proposal(state: AgentState) -> str:
        return "approval" if state.get("proposal") else "report"

    def route_approval(state: AgentState) -> str:
        decision = state.get("approval", {}).get("decision")
        return "execute" if decision == "approve" else "report"

    graph = StateGraph(AgentState)
    graph.add_node("understand", understand_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("collect_evidence", collect_evidence_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("review", review_node)
    graph.add_node("propose", propose_node)
    graph.add_node("approval", approval_node)
    graph.add_node("execute", execute_node)
    graph.add_node("verify", verify_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "retrieve")
    graph.add_edge("retrieve", "collect_evidence")
    graph.add_edge("collect_evidence", "analyst")
    graph.add_edge("analyst", "review")
    graph.add_edge("review", "propose")
    graph.add_conditional_edges("propose", route_proposal, {"approval": "approval", "report": "report"})
    graph.add_conditional_edges("approval", route_approval, {"execute": "execute", "report": "report"})
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)
