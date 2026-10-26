"""Synthetic read-only tools with per-specialist capability checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .models import (
    AgentId,
    ContainerLogSummary,
    ContainerStatus,
    DNSResolution,
    DatastoreStatus,
    Fact,
    HostStatus,
    PermissionDenied,
    RouteStatus,
    RunbookEntry,
    ToolName,
)


class SyntheticToolbox:
    """Answers from fixed in-memory fixtures; it has no external adapters."""

    _DNS_RECORDS: Final = {"api.lab.test": "10.0.0.42"}
    _CONTAINERS: Final = {
        "api": ContainerStatus("api", "running", "10.0.0.24", 8080),
    }

    def invoke(self, tool: ToolName, subject: str) -> Fact:
        if tool is ToolName.DNS_LOOKUP:
            if subject not in self._DNS_RECORDS:
                raise ValueError("unknown_synthetic_domain")
            return DNSResolution(subject, self._DNS_RECORDS[subject])
        if tool is ToolName.ROUTE_STATUS:
            return RouteStatus(subject, reachable=True)
        if tool is ToolName.ESXI_HOST_STATUS:
            if subject != "esxi-lab":
                raise ValueError("unknown_synthetic_host")
            return HostStatus(subject, "connected")
        if tool is ToolName.DATASTORE_STATUS:
            if subject != "datastore-lab":
                raise ValueError("unknown_synthetic_datastore")
            return DatastoreStatus(subject, "healthy", free_percent=64)
        if tool is ToolName.CONTAINER_STATUS:
            if subject not in self._CONTAINERS:
                raise ValueError("unknown_synthetic_container")
            return self._CONTAINERS[subject]
        if tool is ToolName.CONTAINER_LOG_SUMMARY:
            if subject not in self._CONTAINERS:
                raise ValueError("unknown_synthetic_container")
            return ContainerLogSummary(subject, error_count=0)
        if tool is ToolName.RUNBOOK_SEARCH:
            return RunbookEntry(
                topic=subject,
                recommendation="Correct the stale DNS record, then verify the service resolves to its current endpoint.",
            )
        raise ValueError("unknown_synthetic_tool")


@dataclass(frozen=True)
class ToolCapability:
    """One specialist's immutable, independently checked tool allowlist."""

    agent: AgentId
    allowed_tools: frozenset[ToolName]
    _toolbox: SyntheticToolbox

    def call(self, tool: ToolName, subject: str) -> Fact:
        if tool not in self.allowed_tools:
            raise PermissionDenied(f"{self.agent.value} cannot call {tool.value}")
        return self._toolbox.invoke(tool, subject)


NETWORK_TOOLS: Final = frozenset({ToolName.DNS_LOOKUP, ToolName.ROUTE_STATUS})
ESXI_TOOLS: Final = frozenset({ToolName.ESXI_HOST_STATUS, ToolName.DATASTORE_STATUS})
DOCKER_TOOLS: Final = frozenset({ToolName.CONTAINER_STATUS, ToolName.CONTAINER_LOG_SUMMARY})
KNOWLEDGE_TOOLS: Final = frozenset({ToolName.RUNBOOK_SEARCH})


def default_capabilities(toolbox: SyntheticToolbox) -> dict[AgentId, ToolCapability]:
    """Create a distinct capability object for every specialist."""
    grants = {
        AgentId.NETWORK: NETWORK_TOOLS,
        AgentId.ESXI: ESXI_TOOLS,
        AgentId.DOCKER: DOCKER_TOOLS,
        AgentId.KNOWLEDGE: KNOWLEDGE_TOOLS,
    }
    return {
        agent: ToolCapability(agent, frozenset(tools), toolbox)
        for agent, tools in grants.items()
    }
