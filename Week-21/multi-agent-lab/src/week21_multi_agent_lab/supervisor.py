"""Deterministic Supervisor routing, fan-out, handoff, and synthesis."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .models import (
    AgentId,
    ContainerLogSummary,
    ContainerStatus,
    DatastoreStatus,
    DNSResolution,
    EventKind,
    Evidence,
    HostStatus,
    RouteStatus,
    RunResult,
    RoutingDecision,
    ServiceDiagnosis,
    SpecialistReport,
    TaskMessage,
    TaskObjective,
    TraceEvent,
    UnroutableRequest,
)
from .specialists import (
    DockerSpecialist,
    EsxiSpecialist,
    KnowledgeSpecialist,
    NetworkSpecialist,
    Specialist,
)
from .tools import SyntheticToolbox, default_capabilities


class Supervisor:
    """Routes explicit task types to workers and aggregates typed evidence."""

    def __init__(self) -> None:
        capabilities = default_capabilities(SyntheticToolbox())
        self.specialists: dict[AgentId, Specialist] = {
            AgentId.NETWORK: NetworkSpecialist(capabilities[AgentId.NETWORK]),
            AgentId.ESXI: EsxiSpecialist(capabilities[AgentId.ESXI]),
            AgentId.DOCKER: DockerSpecialist(capabilities[AgentId.DOCKER]),
            AgentId.KNOWLEDGE: KnowledgeSpecialist(capabilities[AgentId.KNOWLEDGE]),
        }

    @staticmethod
    def route(question: str) -> RoutingDecision:
        text = question.casefold()
        if any(word in text for word in ("knowledge", "runbook", "procedure")):
            return RoutingDecision(question, (AgentId.KNOWLEDGE,), "knowledge_terms")
        if any(word in text for word in ("outage", "unreachable", "unavailable")):
            if any(word in text for word in ("esxi", "vmware", "datastore")):
                return RoutingDecision(question, (AgentId.ESXI,), "virtualization_outage")
            return RoutingDecision(
                question,
                (AgentId.NETWORK, AgentId.DOCKER),
                "outage_requires_network_and_container_evidence",
            )
        if any(word in text for word in ("dns", "network", "gateway", "route")):
            return RoutingDecision(question, (AgentId.NETWORK,), "network_or_dns_terms")
        if any(word in text for word in ("esxi", "vmware", "datastore", "host status")):
            return RoutingDecision(question, (AgentId.ESXI,), "virtualization_terms")
        if any(word in text for word in ("docker", "container")):
            return RoutingDecision(question, (AgentId.DOCKER,), "container_terms")
        raise UnroutableRequest("request_does_not_match_a_specialist")

    def run(self, question: str) -> RunResult:
        routing = self.route(question)
        trace_id = "week21-demo-001"
        is_outage = routing.specialists == (AgentId.NETWORK, AgentId.DOCKER)
        objectives = {
            AgentId.NETWORK: TaskObjective.DIAGNOSE_SERVICE if is_outage else TaskObjective.CHECK_NETWORK,
            AgentId.ESXI: TaskObjective.CHECK_ESXI,
            AgentId.DOCKER: TaskObjective.DIAGNOSE_SERVICE if is_outage else TaskObjective.CHECK_DOCKER,
            AgentId.KNOWLEDGE: TaskObjective.SEARCH_KNOWLEDGE,
        }
        subjects = {
            AgentId.NETWORK: "api.lab.test",
            AgentId.ESXI: "esxi-lab",
            AgentId.DOCKER: "api",
            AgentId.KNOWLEDGE: "dns",
        }
        tasks = tuple(
            TaskMessage(
                trace_id=trace_id,
                request_id=f"{trace_id}:task:{agent.value}",
                sender=AgentId.SUPERVISOR,
                recipient=agent,
                objective=objectives[agent],
                subject=subjects[agent],
            )
            for agent in routing.specialists
        )
        events = [
            TraceEvent(1, EventKind.ROUTED, AgentId.SUPERVISOR, None, "route-001"),
        ]
        for task in tasks:
            events.append(
                TraceEvent(len(events) + 1, EventKind.TASK_SENT, AgentId.SUPERVISOR,
                           task.recipient, task.request_id)
            )

        workers = [self.specialists[task.recipient] for task in tasks]
        with ThreadPoolExecutor(max_workers=len(workers)) as executor:
            reports = tuple(executor.map(self._execute_task, zip(workers, tasks)))

        for report in reports:
            events.append(
                TraceEvent(len(events) + 1, EventKind.TASK_COMPLETED, report.agent,
                           AgentId.SUPERVISOR, report.request_id,
                           tuple(item.evidence_id for item in report.evidence))
            )

        handoff = None
        handoff_reply = None
        diagnosis = None
        if is_outage:
            network_report = next(report for report in reports if report.agent is AgentId.NETWORK)
            docker_report = next(report for report in reports if report.agent is AgentId.DOCKER)
            network = self.specialists[AgentId.NETWORK]
            assert isinstance(network, NetworkSpecialist)
            handoff = network.prepare_endpoint_handoff(network_report, trace_id=trace_id)
            events.append(
                TraceEvent(len(events) + 1, EventKind.HANDOFF_SENT, handoff.sender,
                           handoff.recipient, handoff.message_id, handoff.evidence_refs)
            )
            docker = self.specialists[AgentId.DOCKER]
            assert isinstance(docker, DockerSpecialist)
            handoff_reply = docker.handle_handoff(
                handoff,
                source_evidence=network_report.evidence,
                local_report=docker_report,
            )
            diagnosis_fact = handoff_reply.evidence.fact
            assert isinstance(diagnosis_fact, ServiceDiagnosis)
            diagnosis = diagnosis_fact
            events.append(
                TraceEvent(len(events) + 1, EventKind.HANDOFF_RECEIVED, AgentId.DOCKER,
                           AgentId.SUPERVISOR, handoff_reply.message_id,
                           handoff_reply.evidence.provenance.source_evidence_ids)
            )
            summary = diagnosis.summary
        else:
            summary = self._summarize(reports[0].evidence)

        events.append(
            TraceEvent(len(events) + 1, EventKind.SYNTHESIZED, AgentId.SUPERVISOR,
                       None, f"{trace_id}:summary")
        )
        return RunResult(
            trace_id=trace_id,
            routing=routing,
            reports=reports,
            handoff=handoff,
            handoff_reply=handoff_reply,
            diagnosis=diagnosis,
            summary=summary,
            events=tuple(events),
        )

    @staticmethod
    def _execute_task(work: tuple[Specialist, TaskMessage]) -> SpecialistReport:
        specialist, task = work
        return specialist.handle(task)

    @staticmethod
    def _summarize(evidence: tuple[Evidence, ...]) -> str:
        summaries = []
        for item in evidence:
            fact = item.fact
            if isinstance(fact, DNSResolution):
                summaries.append(f"{fact.domain} resolves to {fact.address}")
            elif isinstance(fact, RouteStatus):
                summaries.append(f"route to {fact.target}: {'reachable' if fact.reachable else 'unreachable'}")
            elif isinstance(fact, HostStatus):
                summaries.append(f"{fact.host}: {fact.state}")
            elif isinstance(fact, DatastoreStatus):
                summaries.append(f"{fact.datastore}: {fact.state}, {fact.free_percent}% free")
            elif isinstance(fact, ContainerStatus):
                summaries.append(f"{fact.name}: {fact.state} at {fact.address}:{fact.port}")
            elif isinstance(fact, ContainerLogSummary):
                summaries.append(f"{fact.name}: {fact.error_count} log errors")
            else:
                summaries.append(f"{fact.topic}: {fact.recommendation}")
        return "; ".join(summaries)
