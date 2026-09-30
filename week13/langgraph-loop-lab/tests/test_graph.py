from dataclasses import asdict
from pathlib import Path
import socket

import pytest
from agent_loop_lab.agent_loop import run_agent as manual_run, StopReason
from agent_loop_lab.react_model import Decision, ReactModel, StubbornModel
from langsmith import tracing_context

from langgraph_loop_lab.graph import build_graph, initial_state, run_agent
from langgraph_loop_lab.cli import main


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    def no_connect(*args, **kwargs):
        raise AssertionError("This deterministic lab must not access the network")
    monkeypatch.setattr(socket.socket, "connect", no_connect)
    monkeypatch.setattr(socket, "create_connection", no_connect)


def fake_clock(ticks=(0, 0, 0, 0, 0, 0)):
    values = iter(ticks)
    return lambda: next(values, ticks[-1])


@pytest.mark.parametrize("question,actions", [
    ("Diagnose host web01", ["get_host_status", "get_docker_status", "check_alerting"]),
    ("Diagnose host db01", ["get_host_status", "get_docker_status", "check_alerting"]),
    ("Diagnose host esxi01", ["get_host_status"]),
    ("Diagnose host unknown99", ["get_host_status"]),
    ("Diagnose host buggy01", ["get_host_status", "get_docker_status", "check_alerting"]),
    ("What is the status of host db01?", ["get_host_status"]),
    ("Docker on web01", ["get_docker_status"]),
    ("Resolve example.com", ["get_dns_result"]),
    ("Tell me a joke", []),
])
def test_parity_scenarios(question, actions):
    expected = manual_run(question, clock=fake_clock())
    actual = run_agent(question, clock=fake_clock())
    assert asdict(actual.trace) == asdict(expected)
    assert actual.trace.stop_reason == StopReason.FINAL_ANSWER
    assert [step.action for step in actual.trace.steps] == actions
    assert len(actual.state["history"]) == len(actions)
    for current, following in zip(actual.events, actual.events[1:]):
        assert current.next_node == following.node
    assert actual.events[-1].next_node == "__end__"


@pytest.mark.parametrize("max_steps", [-1, 0, 1, 3, 30])
def test_parity_stubborn_limit(max_steps):
    expected = manual_run("host web01", StubbornModel(), max_steps=max_steps, clock=fake_clock())
    actual = run_agent("host web01", StubbornModel(), max_steps=max_steps, clock=fake_clock())
    assert asdict(actual.trace) == asdict(expected)
    assert actual.trace.stop_reason == StopReason.MAX_STEPS_REACHED
    assert len(actual.trace.steps) == max(0, max_steps)


@pytest.mark.parametrize("ticks,max_steps,timeout,reason", [
    ((0, 5), 10, 5, StopReason.TIMEOUT),
    ((0, 0, 5), 10, 5, StopReason.TIMEOUT),
    ((0, 0, 100), 1, 5, StopReason.MAX_STEPS_REACHED),
    ((0, 0), 0, 0, StopReason.MAX_STEPS_REACHED),
])
def test_parity_timeout_priority(ticks, max_steps, timeout, reason):
    options = dict(max_steps=max_steps, timeout_seconds=timeout)
    expected = manual_run("host web01", StubbornModel(), clock=fake_clock(ticks), **options)
    actual = run_agent("host web01", StubbornModel(), clock=fake_clock(ticks), **options)
    assert asdict(actual.trace) == asdict(expected)
    assert actual.trace.stop_reason == reason


class OneAction(ReactModel):
    def __init__(self, action, inputs):
        super().__init__()
        self.action, self.inputs = action, inputs

    def decide(self, question, history):
        if history:
            return Decision("finish after observation", final_answer=history[-1].error or "ok")
        return Decision("exercise tool", action=self.action, action_input=self.inputs)


@pytest.mark.parametrize("action,inputs,error", [
    ("missing_tool", {}, "unknown tool"),
    ("get_host_status", {"host": ""}, "invalid arguments"),
    ("get_host_status", {"host": "missing99"}, "unknown host"),
    ("check_alerting", {"host": "buggy01"}, "unexpected tool error"),
])
def test_parity_tool_errors_become_observations(action, inputs, error):
    expected = manual_run("q", OneAction(action, inputs), clock=fake_clock())
    actual = run_agent("q", OneAction(action, inputs), clock=fake_clock())
    assert asdict(actual.trace) == asdict(expected)
    assert error in actual.state["history"][0].error
    assert actual.trace.stop_reason == StopReason.FINAL_ANSWER


def test_parity_empty_decision_and_final_elapsed():
    class EmptyModel(ReactModel):
        def decide(self, question, history):
            return Decision("no action or answer")
    expected = manual_run("q", EmptyModel(), clock=fake_clock((1, 2, 7)))
    actual = run_agent("q", EmptyModel(), clock=fake_clock((1, 2, 7)))
    assert asdict(actual.trace) == asdict(expected)
    assert actual.trace.final_answer == ""


def test_model_receives_accumulation_and_expected_node_order():
    model = ReactModel()
    result = run_agent("Diagnose host web01", model, clock=fake_clock())
    assert [entry.rsplit("=", 1)[1] for entry in model.call_log] == ["0", "1", "2", "3"]
    assert [event.node for event in result.events] == ["guard", "decide", "act"] * 3 + ["guard", "decide", "finish"]
    assert [event.history_size for event in result.events if event.node == "act"] == [1, 2, 3]
    assert len(result.state["steps"]) == len(result.state["history"]) == 3


def test_partial_updates_do_not_mutate_input_and_reducers_append():
    state = initial_state("Diagnose host web01", 6, 10, 0)
    with tracing_context(enabled=False):
        updates = list(build_graph(clock=fake_clock()).stream(state, stream_mode="updates"))
    act_updates = [update["act"] for update in updates if "act" in update]
    assert len(act_updates) == 3
    assert all(len(delta["history"]) == len(delta["steps"]) == len(delta["events"]) == 1 for delta in act_updates)
    assert all("question" not in delta for delta in act_updates)
    assert state["history"] == state["steps"] == state["events"] == []
    result = run_agent("Diagnose host web01", clock=fake_clock())
    assert len(result.events) == len(updates)


def test_diagram_and_edge_types_match_compiled_graph():
    graph = build_graph().get_graph()
    edges = {(edge.source, edge.target, edge.conditional) for edge in graph.edges}
    assert edges == {("__start__", "guard", False), ("guard", "decide", True),
                     ("guard", "finish", True), ("decide", "act", True),
                     ("decide", "finish", True), ("act", "guard", False), ("finish", "__end__", False)}
    saved = Path(__file__).resolve().parents[1] / "docs/agent-state-graph.mmd"
    assert saved.read_text(encoding="utf-8").strip() == graph.draw_mermaid().strip()


def test_runs_have_independent_state():
    first = run_agent("Diagnose host web01", clock=fake_clock())
    second = run_agent("Tell me a joke", clock=fake_clock())
    assert len(first.trace.steps) == 3
    assert second.state["history"] == []
    assert [e.node for e in second.events] == ["guard", "decide", "finish"]


def test_cli_question_diagram_and_demo(capsys):
    assert main(["Diagnose host esxi01"]) == 0
    output = capsys.readouterr().out
    assert "decide -> finish" in output and "DOWN" in output
    assert "tool[2]" not in output
    assert main(["--diagram"]) == 0
    assert "graph TD" in capsys.readouterr().out
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "stop_reason=max_steps_reached" in output
    assert "stop_reason=timeout" in output
