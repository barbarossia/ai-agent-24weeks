"""Network, ESXi, Docker, and Knowledge workers."""

from __future__ import annotations

from .models import (
    AgentId,
    ContainerStatus,
    DNSResolution,
    DiagnosisCause,
    Evidence,
    Fact,
    HandoffMessage,
    HandoffPurpose,
    HandoffReply,
    HostStatus,
    InvalidHandoff,
    Provenance,
    RouteStatus,
    ServiceDiagnosis,
    SpecialistReport,
    TaskMessage,
    TaskObjective,
    ToolName,
)
from .tools import ToolCapability


class Specialist:
    def __init__(self, capability: ToolCapability):
        self.capability = capability
        self.agent = capability.agent

    def _check_task(self, task: TaskMessage) -> None:
        if task.recipient is not self.agent:
            raise ValueError("task_recipient_mismatch")

    def handle(self, task: TaskMessage) -> SpecialistReport:
        raise NotImplementedError

    def _evidence(self, task: TaskMessage, suffix: str, tool: ToolName, fact: Fact) -> Evidence:
        return Evidence(
            evidence_id=f"{task.request_id}:{suffix}",
            fact=fact,
            provenance=Provenance(self.agent, tool, task.request_id),
        )


class NetworkSpecialist(Specialist):
    def handle(self, task: TaskMessage) -> SpecialistReport:
        self._check_task(task)
        if task.objective not in {TaskObjective.CHECK_NETWORK, TaskObjective.DIAGNOSE_SERVICE}:
            raise ValueError("unsupported_network_objective")
        dns = self.capability.call(ToolName.DNS_LOOKUP, task.subject)
        route = self.capability.call(ToolName.ROUTE_STATUS, task.subject)
        evidence = (
            self._evidence(task, "dns", ToolName.DNS_LOOKUP, dns),
            self._evidence(task, "route", ToolName.ROUTE_STATUS, route),
        )
        return SpecialistReport(self.agent, task.request_id, evidence)

    def prepare_endpoint_handoff(
        self, report: SpecialistReport, *, trace_id: str
    ) -> HandoffMessage:
        if report.agent is not self.agent or not any(
            isinstance(item.fact, DNSResolution) for item in report.evidence
        ):
            raise InvalidHandoff("network_report_invalid")
        return HandoffMessage(
            trace_id=trace_id,
            message_id=f"{trace_id}:handoff:network-to-docker",
            sender=self.agent,
            recipient=AgentId.DOCKER,
            purpose=HandoffPurpose.CORRELATE_SERVICE_ENDPOINT,
            prompt="Compare the DNS and route evidence with the container's local endpoint.",
            evidence_refs=tuple(item.evidence_id for item in report.evidence),
        )


class EsxiSpecialist(Specialist):
    def handle(self, task: TaskMessage) -> SpecialistReport:
        self._check_task(task)
        if task.objective is not TaskObjective.CHECK_ESXI:
            raise ValueError("unsupported_esxi_objective")
        host = self.capability.call(ToolName.ESXI_HOST_STATUS, task.subject)
        datastore = self.capability.call(ToolName.DATASTORE_STATUS, "datastore-lab")
        evidence = (
            self._evidence(task, "host", ToolName.ESXI_HOST_STATUS, host),
            self._evidence(task, "datastore", ToolName.DATASTORE_STATUS, datastore),
        )
        return SpecialistReport(self.agent, task.request_id, evidence)


class DockerSpecialist(Specialist):
    def handle(self, task: TaskMessage) -> SpecialistReport:
        self._check_task(task)
        if task.objective not in {TaskObjective.CHECK_DOCKER, TaskObjective.DIAGNOSE_SERVICE}:
            raise ValueError("unsupported_docker_objective")
        container = self.capability.call(ToolName.CONTAINER_STATUS, task.subject)
        logs = self.capability.call(ToolName.CONTAINER_LOG_SUMMARY, task.subject)
        evidence = (
            self._evidence(task, "container", ToolName.CONTAINER_STATUS, container),
            self._evidence(task, "logs", ToolName.CONTAINER_LOG_SUMMARY, logs),
        )
        return SpecialistReport(self.agent, task.request_id, evidence)

    def handle_handoff(
        self,
        message: HandoffMessage,
        *,
        source_evidence: tuple[Evidence, ...],
        local_report: SpecialistReport,
    ) -> HandoffReply:
        if message.sender is not AgentId.NETWORK or message.recipient is not self.agent:
            raise InvalidHandoff("handoff_participants_invalid")
        if message.purpose is not HandoffPurpose.CORRELATE_SERVICE_ENDPOINT:
            raise InvalidHandoff("handoff_purpose_invalid")
        if local_report.agent is not self.agent:
            raise InvalidHandoff("local_report_agent_invalid")

        by_id = {evidence.evidence_id: evidence for evidence in source_evidence}
        if not message.evidence_refs or any(ref not in by_id for ref in message.evidence_refs):
            raise InvalidHandoff("handoff_evidence_missing")
        referenced = tuple(by_id[ref] for ref in message.evidence_refs)
        if any(item.provenance.agent is not message.sender for item in referenced):
            raise InvalidHandoff("handoff_evidence_provenance_invalid")

        dns = next((item.fact for item in referenced if isinstance(item.fact, DNSResolution)), None)
        route = next((item.fact for item in referenced if isinstance(item.fact, RouteStatus)), None)
        container = next(
            (item.fact for item in local_report.evidence if isinstance(item.fact, ContainerStatus)),
            None,
        )
        if dns is None or route is None or container is None:
            raise InvalidHandoff("handoff_facts_incomplete")

        if not route.reachable:
            cause = DiagnosisCause.NETWORK_UNREACHABLE
            summary = f"The route to {route.target} is unreachable."
        elif container.state != "running":
            cause = DiagnosisCause.CONTAINER_UNHEALTHY
            summary = f"Container {container.name} is {container.state}."
        elif dns.address != container.address:
            cause = DiagnosisCause.STALE_DNS
            summary = (
                f"DNS for {dns.domain} resolves to {dns.address}, while the healthy "
                f"{container.name} container listens at {container.address}:{container.port}."
            )
        else:
            cause = DiagnosisCause.NO_FAULT_FOUND
            summary = f"DNS and the {container.name} container endpoint agree."

        source_ids = tuple(message.evidence_refs) + tuple(
            item.evidence_id for item in local_report.evidence
        )
        evidence = Evidence(
            evidence_id=f"{message.message_id}:diagnosis",
            fact=ServiceDiagnosis(cause, summary),
            provenance=Provenance(
                agent=self.agent,
                tool=None,
                request_id=message.message_id,
                source_evidence_ids=source_ids,
            ),
        )
        return HandoffReply(
            trace_id=message.trace_id,
            message_id=f"{message.message_id}:reply",
            sender=self.agent,
            recipient=AgentId.SUPERVISOR,
            evidence=evidence,
        )


class KnowledgeSpecialist(Specialist):
    def handle(self, task: TaskMessage) -> SpecialistReport:
        self._check_task(task)
        if task.objective is not TaskObjective.SEARCH_KNOWLEDGE:
            raise ValueError("unsupported_knowledge_objective")
        entry = self.capability.call(ToolName.RUNBOOK_SEARCH, task.subject)
        evidence = self._evidence(task, "runbook", ToolName.RUNBOOK_SEARCH, entry)
        return SpecialistReport(self.agent, task.request_id, (evidence,))
