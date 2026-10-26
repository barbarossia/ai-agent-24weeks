from __future__ import annotations

import re
from typing import Any

from .models import AgentHandoff, Citation, Diagnosis, ReviewResult, ToolObservation


CAUSE_SOURCE = {
    "route_mismatch": "knowledge/netflix-routing.md",
    "node_unhealthy": "knowledge/egress-node-health.md",
    "dns_stale_target": "knowledge/dns-cache.md",
    "proxy_unhealthy": "knowledge/netflix-routing.md",
}


def _citations(values: list[dict[str, Any]]) -> tuple[Citation, ...]:
    return tuple(Citation.model_validate(item) for item in values)


def _observations(values: dict[str, dict[str, Any]]) -> tuple[ToolObservation, ...]:
    result: list[ToolObservation] = []
    for name, data in values.items():
        result.append(ToolObservation(tool=name, evidence_id=data["evidence_id"], data=data))
        if name == "read_recent_logs":
            result.extend(
                ToolObservation(tool=name, evidence_id=event["evidence_id"], data=event)
                for event in data.get("events", [])
                if isinstance(event, dict) and isinstance(event.get("evidence_id"), str)
            )
    return tuple(result)


def _knowledge_fact(citations: tuple[Citation, ...], source: str, pattern: str) -> str | None:
    for citation in citations:
        if citation.source != source:
            continue
        match = re.search(pattern, citation.excerpt, re.I)
        if match:
            return match.group(1)
    return None


def _event_evidence_id(observations: dict[str, dict[str, Any]], code: str) -> str | None:
    return next((
        event.get("evidence_id")
        for event in observations["read_recent_logs"].get("events", [])
        if isinstance(event, dict)
        and event.get("code") == code
        and isinstance(event.get("evidence_id"), str)
    ), None)


def _diagnosis_evidence_ids(code: str, observations: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    primary_tool = {
        "route_mismatch": "inspect_routing_rule",
        "node_unhealthy": "node_health",
        "dns_stale_target": "dns_lookup",
        "proxy_unhealthy": "proxy_health",
    }.get(code)
    event_code = {
        "route_mismatch": "RULE_DIRECT_BLOCK",
        "node_unhealthy": "NODE_DRAINING",
        "dns_stale_target": "DNS_STALE_TARGET",
        "proxy_unhealthy": "PROXY_POOL_UNHEALTHY",
    }.get(code)
    if not primary_tool or not event_code:
        return ()
    primary_id = observations[primary_tool].get("evidence_id")
    event_id = _event_evidence_id(observations, event_code)
    return tuple(item for item in (primary_id, event_id) if isinstance(item, str))


def _corroborated_diagnosis(
    evidence: tuple[ToolObservation, ...], citations: tuple[Citation, ...]
) -> tuple[str, tuple[str, ...]] | None:
    by_id = {item.evidence_id: item for item in evidence}
    by_code = {
        item.data.get("code"): item
        for item in evidence
        if item.tool == "read_recent_logs" and item.data.get("code")
    }
    rule = next((item for item in evidence if item.tool == "inspect_routing_rule"), None)
    node = next((item for item in evidence if item.tool == "node_health"), None)
    dns = next((item for item in evidence if item.tool == "dns_lookup"), None)
    proxy = next((item for item in evidence if item.tool == "proxy_health"), None)

    expected_route = _knowledge_fact(
        citations, "knowledge/netflix-routing.md", r"should use the `([A-Z]+)` action"
    )
    if (
        rule and expected_route and rule.data.get("action") != expected_route
        and "RULE_DIRECT_BLOCK" in by_code
    ):
        ids = (rule.evidence_id, by_code["RULE_DIRECT_BLOCK"].evidence_id)
        return "route_mismatch", tuple(item for item in ids if item in by_id)

    expected_node_status = _knowledge_fact(
        citations, "knowledge/egress-node-health.md", r"active egress node must report `([a-z]+)`"
    )
    if (
        node and expected_node_status and node.data.get("status") != expected_node_status
        and "NODE_DRAINING" in by_code
    ):
        ids = (node.evidence_id, by_code["NODE_DRAINING"].evidence_id)
        return "node_unhealthy", tuple(item for item in ids if item in by_id)

    expected_dns_answer = _knowledge_fact(
        citations,
        "knowledge/dns-cache.md",
        r"expected synthetic `netflix\.com` address is `([0-9.]+)`",
    )
    if (
        dns and expected_dns_answer and dns.data.get("answers") != [expected_dns_answer]
        and "DNS_STALE_TARGET" in by_code
    ):
        ids = (dns.evidence_id, by_code["DNS_STALE_TARGET"].evidence_id)
        return "dns_stale_target", tuple(item for item in ids if item in by_id)

    if proxy and proxy.data.get("healthy") is False and "PROXY_POOL_UNHEALTHY" in by_code:
        ids = (proxy.evidence_id, by_code["PROXY_POOL_UNHEALTHY"].evidence_id)
        return "proxy_unhealthy", tuple(item for item in ids if item in by_id)
    return None


class DiagnosticAnalyst:
    """Deterministic specialist that reasons only over typed fixture fields and event codes."""

    name = "diagnostic-analyst"

    def analyze(
        self,
        *,
        case_id: str,
        observations: dict[str, dict[str, Any]],
        citations: list[dict[str, Any]],
    ) -> AgentHandoff:
        event_codes = {
            event.get("code")
            for event in observations["read_recent_logs"].get("events", [])
            if isinstance(event, dict)
        }
        dns = observations["dns_lookup"]
        node = observations["node_health"]
        rule = observations["inspect_routing_rule"]
        proxy = observations["proxy_health"]
        retrieved = _citations(citations)
        expected_route = _knowledge_fact(
            retrieved,
            "knowledge/netflix-routing.md",
            r"should use the `([A-Z]+)` action",
        )
        expected_node_status = _knowledge_fact(
            retrieved,
            "knowledge/egress-node-health.md",
            r"active egress node must report `([a-z]+)`",
        )
        expected_dns_answer = _knowledge_fact(
            retrieved,
            "knowledge/dns-cache.md",
            r"expected synthetic `netflix\.com` address is `([0-9.]+)`",
        )

        if expected_route and rule["action"] != expected_route and "RULE_DIRECT_BLOCK" in event_codes:
            code, summary, confidence = (
                "route_mismatch", "The Netflix route selects direct egress instead of the media proxy.", 0.98
            )
        elif expected_node_status and node["status"] != expected_node_status and "NODE_DRAINING" in event_codes:
            code, summary, confidence = (
                "node_unhealthy", "The active Netflix egress node is draining.", 0.97
            )
        elif expected_dns_answer and dns["answers"] != [expected_dns_answer] and "DNS_STALE_TARGET" in event_codes:
            code, summary, confidence = (
                "dns_stale_target", "The Netflix DNS cache returns an obsolete fixture address.", 0.97
            )
        elif not proxy["healthy"] and "PROXY_POOL_UNHEALTHY" in event_codes:
            code, summary, confidence = (
                "proxy_unhealthy", "The synthetic media proxy pool is unhealthy.", 0.95
            )
        else:
            code, summary, confidence = (
                "inconclusive", "The fixture evidence does not establish a supported cause.", 0.2
            )

        relevant_source = CAUSE_SOURCE.get(code)
        relevant_citations = tuple(
            citation for citation in retrieved if citation.source == relevant_source
        )[:2]
        diagnosis = Diagnosis(
            cause_code=code,
            summary=summary,
            confidence=confidence,
            evidence_ids=_diagnosis_evidence_ids(code, observations),
            citations=relevant_citations,
        )
        return AgentHandoff(
            task_id=case_id,
            sender=self.name,
            recipient="sre-reviewer",
            diagnosis=diagnosis,
            evidence=_observations(observations),
        )


class IndependentSREReviewer:
    """Second local agent accepts only corroborated causes with a retrieved citation."""

    name = "sre-reviewer"

    def review(self, handoff_data: dict[str, Any]) -> ReviewResult:
        handoff = AgentHandoff.model_validate(handoff_data)
        evidence = {item.evidence_id: item for item in handoff.evidence}
        corroboration = _corroborated_diagnosis(handoff.evidence, handoff.diagnosis.citations)
        cited_evidence = tuple(
            evidence_id for evidence_id in handoff.diagnosis.evidence_ids if evidence_id in evidence
        )
        distinct_tools = {evidence[evidence_id].tool for evidence_id in cited_evidence}
        sources = handoff.diagnosis.citations
        accepted = (
            handoff.protocol == "local-a2a/1"
            and handoff.recipient == self.name
            and corroboration is not None
            and handoff.diagnosis.cause_code == corroboration[0]
            and handoff.diagnosis.confidence >= 0.9
            and set(cited_evidence) == set(corroboration[1])
            and len(distinct_tools) >= 2
            and bool(sources)
            and all(item.source == CAUSE_SOURCE.get(handoff.diagnosis.cause_code) for item in sources)
        )
        return ReviewResult(
            accepted=accepted,
            reviewer=self.name,
            rationale=(
                "Cause has independent fixture evidence and a cited local runbook."
                if accepted else "Cause lacks a valid handoff, corroboration, confidence, or citation."
            ),
            corroborating_evidence=cited_evidence,
            citations=sources,
        )
