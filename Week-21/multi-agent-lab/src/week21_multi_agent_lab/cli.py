"""Console output for the deterministic outage collaboration demo."""

from __future__ import annotations

from .comparison import compare_with_single_agent
from .models import AgentId
from .supervisor import Supervisor


def main() -> int:
    supervisor = Supervisor()
    result = supervisor.run("Diagnose the API service outage at api.lab.test")
    print("scenario=service_outage status=PASS")
    print("route=" + ",".join(agent.value for agent in result.routing.specialists))
    print("dispatch=parallel")
    for report in result.reports:
        tools = ",".join(
            item.provenance.tool.value
            for item in report.evidence
            if item.provenance.tool is not None
        )
        print(f"worker={report.agent.value} evidence={len(report.evidence)} tools={tools}")
    assert result.handoff is not None and result.handoff_reply is not None
    print(
        f"handoff={result.handoff.sender.value}->{result.handoff.recipient.value} "
        f"evidence_refs={len(result.handoff.evidence_refs)}"
    )
    print(f"diagnosis={result.diagnosis.cause.value if result.diagnosis else 'missing'}")
    print(f"summary={result.summary}")
    print("provenance=" + ",".join(result.handoff_reply.evidence.provenance.source_evidence_ids))
    print("permission_matrix:")
    for agent in (AgentId.NETWORK, AgentId.ESXI, AgentId.DOCKER, AgentId.KNOWLEDGE):
        capability = supervisor.specialists[agent].capability
        tools = ",".join(sorted(tool.value for tool in capability.allowed_tools))
        print(f"  {agent.value}: {tools}")
    print("comparison:")
    for row in compare_with_single_agent(result):
        print(
            f"  {row.dimension.value}: supervisor_worker=[{row.supervisor_worker}] "
            f"single_agent=[{row.single_agent_with_tools}]"
        )
    return 0
