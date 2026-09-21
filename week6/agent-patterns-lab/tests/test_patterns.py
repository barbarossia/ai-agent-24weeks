"""Comprehensive test suite and smoke tests for all 4 agent patterns."""

from agent_patterns_lab.pattern1_single_tool import SingleAgentWithTools
from agent_patterns_lab.pattern2_pipeline import SequentialPipeline
from agent_patterns_lab.pattern3_router import RouterDispatcher
from agent_patterns_lab.pattern4_supervisor import SupervisorAgent


def test_pattern1_single_tool_host():
    agent = SingleAgentWithTools()
    trace = agent.run("Check status of host web01")
    assert trace.pattern_name.startswith("1.")
    assert "web01" in trace.output
    assert "up" in trace.output
    assert len(trace.steps) >= 3


def test_pattern1_single_tool_docker():
    agent = SingleAgentWithTools()
    trace = agent.run("List docker containers on db01")
    assert "postgres" in trace.output or "2 containers" in trace.output
    assert any("get_docker_status" in s for s in trace.steps)


def test_pattern1_direct_answer():
    agent = SingleAgentWithTools()
    trace = agent.run("What is your name?")
    assert "I can answer" in trace.output
    assert any("direct answer" in s for s in trace.steps)


def test_pattern2_pipeline_healthy():
    pipeline = SequentialPipeline()
    trace = pipeline.run("web01")
    assert trace.pattern_name.startswith("2.")
    assert "Overall Status: [OK]" in trace.output
    assert any("Stage 1" in s for s in trace.steps)
    assert any("Stage 2" in s for s in trace.steps)
    assert any("Stage 3" in s for s in trace.steps)


def test_pattern2_pipeline_warning_and_down():
    pipeline = SequentialPipeline()
    trace_db = pipeline.run("db01")
    assert "High CPU" in trace_db.output
    assert "[ATTENTION NEEDED]" in trace_db.output

    trace_down = pipeline.run("esxi01")
    assert "Host status is down" in trace_down.output
    assert "[ATTENTION NEEDED]" in trace_down.output


def test_pattern3_router_network():
    router = RouterDispatcher()
    trace = router.run("Check OpenWrt network gateway status")
    assert trace.pattern_name.startswith("3.")
    assert "[NetworkSpecialist]" in trace.output
    assert "192.168.1.1" in trace.output


def test_pattern3_router_docker():
    router = RouterDispatcher()
    trace = router.run("Check docker containers status")
    assert "[DockerSpecialist]" in trace.output
    assert "nginx" in trace.output


def test_pattern3_router_host():
    router = RouterDispatcher()
    trace = router.run("What is the CPU utilization of servers?")
    assert "[HostSpecialist]" in trace.output
    assert "web01" in trace.output


def test_pattern4_supervisor_full_audit():
    supervisor = SupervisorAgent()
    trace = supervisor.run(["web01", "db01", "esxi01"])
    assert trace.pattern_name.startswith("4.")
    assert "=== Supervisor Multi-Agent Audit Summary ===" in trace.output
    assert "Host web01 [PASS]" in trace.output
    assert "Host db01 [FAIL]" in trace.output
    assert "CPU usage exceeds 85%" in trace.output
    assert "Host esxi01 [FAIL]" in trace.output
    assert "Host is offline" in trace.output
    assert any("DiagnosticWorker" in s for s in trace.steps)
    assert any("PolicyAuditWorker" in s for s in trace.steps)
