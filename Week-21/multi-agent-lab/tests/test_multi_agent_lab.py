import unittest

from week21_multi_agent_lab.comparison import ComparisonDimension, compare_with_single_agent
from week21_multi_agent_lab.models import (
    AgentId,
    DiagnosisCause,
    EventKind,
    PermissionDenied,
    ToolName,
)
from week21_multi_agent_lab.supervisor import Supervisor


class MultiAgentLabTests(unittest.TestCase):
    def test_supervisor_routes_to_the_matching_specialist(self):
        expected = {
            "Check DNS for api.lab.test": (AgentId.NETWORK,),
            "Check ESXi host status": (AgentId.ESXI,),
            "Check Docker container status": (AgentId.DOCKER,),
            "Find the DNS runbook procedure": (AgentId.KNOWLEDGE,),
            "Diagnose the API service outage": (AgentId.NETWORK, AgentId.DOCKER),
            "Docker service outage": (AgentId.NETWORK, AgentId.DOCKER),
            "DNS outage for api.lab.test": (AgentId.NETWORK, AgentId.DOCKER),
            "ESXi host outage": (AgentId.ESXI,),
            "Find the runbook procedure for a DNS outage": (AgentId.KNOWLEDGE,),
        }
        for question, specialists in expected.items():
            with self.subTest(question=question):
                self.assertEqual(Supervisor.route(question).specialists, specialists)

    def test_specialist_capabilities_are_independent_and_enforced(self):
        supervisor = Supervisor()
        expected = {
            AgentId.NETWORK: {ToolName.DNS_LOOKUP, ToolName.ROUTE_STATUS},
            AgentId.ESXI: {ToolName.ESXI_HOST_STATUS, ToolName.DATASTORE_STATUS},
            AgentId.DOCKER: {ToolName.CONTAINER_STATUS, ToolName.CONTAINER_LOG_SUMMARY},
            AgentId.KNOWLEDGE: {ToolName.RUNBOOK_SEARCH},
        }
        capabilities = {
            agent: supervisor.specialists[agent].capability for agent in expected
        }
        self.assertEqual(len({id(capability) for capability in capabilities.values()}), 4)
        for agent, allowed_tools in expected.items():
            capability = capabilities[agent]
            with self.subTest(agent=agent):
                self.assertEqual(capability.allowed_tools, frozenset(allowed_tools))
                for tool in set(ToolName) - allowed_tools:
                    with self.assertRaises(PermissionDenied):
                        capability.call(tool, "synthetic-subject")
        network = capabilities[AgentId.NETWORK]
        docker = capabilities[AgentId.DOCKER]
        self.assertIsNot(network, docker)
        self.assertEqual(docker.call(ToolName.CONTAINER_STATUS, "api").state, "running")

    def test_outage_handoff_combines_network_and_docker_provenance(self):
        result = Supervisor().run("Diagnose the API service outage at api.lab.test")

        self.assertIsNotNone(result.handoff)
        self.assertIsNotNone(result.handoff_reply)
        self.assertIs(result.handoff.sender, AgentId.NETWORK)
        self.assertIs(result.handoff.recipient, AgentId.DOCKER)
        self.assertIsNotNone(result.diagnosis)
        self.assertIs(result.diagnosis.cause, DiagnosisCause.STALE_DNS)
        network_ids = {item.evidence_id for item in result.reports[0].evidence}
        docker_ids = {item.evidence_id for item in result.reports[1].evidence}
        provenance_ids = set(result.handoff_reply.evidence.provenance.source_evidence_ids)
        self.assertEqual(set(result.handoff.evidence_refs), network_ids)
        self.assertLessEqual(network_ids | docker_ids, provenance_ids)
        self.assertIs(result.handoff_reply.evidence.provenance.agent, AgentId.DOCKER)
        self.assertTrue(any(event.kind is EventKind.HANDOFF_SENT for event in result.events))
        self.assertTrue(any(event.kind is EventKind.HANDOFF_RECEIVED for event in result.events))
        self.assertIn("10.0.0.42", result.summary)
        self.assertIn("10.0.0.24", result.summary)

    def test_each_specialist_executes_only_its_granted_fixture_tools(self):
        supervisor = Supervisor()
        esxi = supervisor.run("Check ESXi host status")
        knowledge = supervisor.run("Find the DNS runbook procedure")

        self.assertEqual(
            {item.provenance.tool for item in esxi.reports[0].evidence},
            {ToolName.ESXI_HOST_STATUS, ToolName.DATASTORE_STATUS},
        )
        self.assertEqual(
            {item.provenance.tool for item in knowledge.reports[0].evidence},
            {ToolName.RUNBOOK_SEARCH},
        )

    def test_comparison_covers_tradeoffs_and_explicit_cost_assumptions(self):
        result = Supervisor().run("Diagnose the API service outage")
        rows = compare_with_single_agent(result)

        self.assertEqual({row.dimension for row in rows}, set(ComparisonDimension))
        cost = next(row for row in rows if row.dimension is ComparisonDimension.COST)
        self.assertIn("$0.00", cost.supervisor_worker)
        self.assertIn("$0.00", cost.single_agent_with_tools)
        self.assertIn("4 tool reads", cost.supervisor_worker)
        self.assertIn("not measured", cost.assumption)
        isolation = next(row for row in rows if row.dimension is ComparisonDimension.ISOLATION)
        self.assertIn("logical separation only", isolation.supervisor_worker)
