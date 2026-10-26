"""Typed messages, evidence, and provenance for the Week 21 lab."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentId(str, Enum):
    SUPERVISOR = "supervisor"
    NETWORK = "network"
    ESXI = "esxi"
    DOCKER = "docker"
    KNOWLEDGE = "knowledge"


class TaskObjective(str, Enum):
    CHECK_NETWORK = "check_network"
    CHECK_ESXI = "check_esxi"
    CHECK_DOCKER = "check_docker"
    SEARCH_KNOWLEDGE = "search_knowledge"
    DIAGNOSE_SERVICE = "diagnose_service"


class ToolName(str, Enum):
    DNS_LOOKUP = "dns_lookup"
    ROUTE_STATUS = "route_status"
    ESXI_HOST_STATUS = "esxi_host_status"
    DATASTORE_STATUS = "datastore_status"
    CONTAINER_STATUS = "container_status"
    CONTAINER_LOG_SUMMARY = "container_log_summary"
    RUNBOOK_SEARCH = "runbook_search"


class HandoffPurpose(str, Enum):
    CORRELATE_SERVICE_ENDPOINT = "correlate_service_endpoint"


class DiagnosisCause(str, Enum):
    STALE_DNS = "stale_dns"
    NETWORK_UNREACHABLE = "network_unreachable"
    CONTAINER_UNHEALTHY = "container_unhealthy"
    NO_FAULT_FOUND = "no_fault_found"


class EventKind(str, Enum):
    ROUTED = "routed"
    TASK_SENT = "task_sent"
    TASK_COMPLETED = "task_completed"
    HANDOFF_SENT = "handoff_sent"
    HANDOFF_RECEIVED = "handoff_received"
    SYNTHESIZED = "synthesized"


class PermissionDenied(PermissionError):
    """Raised when an agent requests a tool outside its own capability set."""


class UnroutableRequest(ValueError):
    """Raised when the deterministic router cannot identify a specialist."""


class InvalidHandoff(ValueError):
    """Raised when a handoff recipient, sender, or evidence reference is invalid."""


@dataclass(frozen=True)
class TaskMessage:
    trace_id: str
    request_id: str
    sender: AgentId
    recipient: AgentId
    objective: TaskObjective
    subject: str


@dataclass(frozen=True)
class HandoffMessage:
    trace_id: str
    message_id: str
    sender: AgentId
    recipient: AgentId
    purpose: HandoffPurpose
    prompt: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class Provenance:
    agent: AgentId
    tool: ToolName | None
    request_id: str
    source_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DNSResolution:
    domain: str
    address: str


@dataclass(frozen=True)
class RouteStatus:
    target: str
    reachable: bool


@dataclass(frozen=True)
class HostStatus:
    host: str
    state: str


@dataclass(frozen=True)
class DatastoreStatus:
    datastore: str
    state: str
    free_percent: int


@dataclass(frozen=True)
class ContainerStatus:
    name: str
    state: str
    address: str
    port: int


@dataclass(frozen=True)
class ContainerLogSummary:
    name: str
    error_count: int


@dataclass(frozen=True)
class RunbookEntry:
    topic: str
    recommendation: str


@dataclass(frozen=True)
class ServiceDiagnosis:
    cause: DiagnosisCause
    summary: str


Fact = (
    DNSResolution
    | RouteStatus
    | HostStatus
    | DatastoreStatus
    | ContainerStatus
    | ContainerLogSummary
    | RunbookEntry
    | ServiceDiagnosis
)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    fact: Fact
    provenance: Provenance


@dataclass(frozen=True)
class SpecialistReport:
    agent: AgentId
    request_id: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class HandoffReply:
    trace_id: str
    message_id: str
    sender: AgentId
    recipient: AgentId
    evidence: Evidence


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    kind: EventKind
    actor: AgentId
    recipient: AgentId | None
    message_id: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingDecision:
    question: str
    specialists: tuple[AgentId, ...]
    reason: str


@dataclass(frozen=True)
class RunResult:
    trace_id: str
    routing: RoutingDecision
    reports: tuple[SpecialistReport, ...]
    handoff: HandoffMessage | None
    handoff_reply: HandoffReply | None
    diagnosis: ServiceDiagnosis | None
    summary: str
    events: tuple[TraceEvent, ...]
