"""Explicit nodes, partial updates and routes; no wrapper around the Week 5 loop."""

from dataclasses import dataclass
from operator import add
import time
from typing import Annotated, Callable, TypedDict

from agent_loop_lab.agent_loop import AgentStep, AgentTrace, StopReason, _execute_action
from agent_loop_lab.react_model import Decision, Observation, ReactModel
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context


@dataclass(frozen=True)
class NodeEvent:
    node: str
    next_node: str
    completed_steps: int
    history_size: int
    detail: str


class AgentState(TypedDict):
    question: str
    max_steps: int
    timeout_seconds: float
    started_at: float
    completed_steps: int
    decision: Decision | None
    next_node: str
    history: Annotated[list[Observation], add]
    steps: Annotated[list[AgentStep], add]
    events: Annotated[list[NodeEvent], add]
    final_answer: str | None
    stop_reason: StopReason | None
    elapsed_seconds: float


@dataclass
class GraphRun:
    trace: AgentTrace
    state: AgentState

    @property
    def events(self) -> list[NodeEvent]:
        return self.state["events"]


def initial_state(question, max_steps, timeout_seconds, started_at) -> AgentState:
    return dict(question=question, max_steps=max_steps, timeout_seconds=timeout_seconds,
                started_at=started_at, completed_steps=0, decision=None, next_node="guard",
                history=[], steps=[], events=[], final_answer=None, stop_reason=None,
                elapsed_seconds=0.0)


def build_graph(model: ReactModel | None = None, clock: Callable[[], float] = time.monotonic):
    model = model if model is not None else ReactModel()

    def event(state, node, next_node, detail, completed=None):
        count = state["completed_steps"] if completed is None else completed
        return NodeEvent(node, next_node, count, count, detail)

    def guard(state: AgentState):
        # Week 5 exits the for-loop before another timeout check when no iterations remain.
        if state["completed_steps"] >= state["max_steps"]:
            return {"stop_reason": StopReason.MAX_STEPS_REACHED, "next_node": "finish",
                    "events": [event(state, "guard", "finish", "max_steps_reached")]}
        elapsed = clock() - state["started_at"]
        if elapsed >= state["timeout_seconds"]:
            return {"stop_reason": StopReason.TIMEOUT, "elapsed_seconds": elapsed,
                    "next_node": "finish", "events": [event(state, "guard", "finish", "timeout")]}
        return {"next_node": "decide", "events": [event(state, "guard", "decide", "budget available")]}

    def decide(state: AgentState):
        decision = model.decide(state["question"], list(state["history"]))
        if decision.action is None:
            return {"decision": decision, "stop_reason": StopReason.FINAL_ANSWER,
                    "final_answer": decision.final_answer or "", "next_node": "finish",
                    "events": [event(state, "decide", "finish", decision.thought)]}
        return {"decision": decision, "next_node": "act",
                "events": [event(state, "decide", "act", decision.thought)]}

    def act(state: AgentState):
        decision = state["decision"]
        assert decision is not None and decision.action is not None
        # Deliberate private-helper reuse: retains all four Week 5 tool error translations.
        observation = _execute_action(decision.action, decision.action_input or {})
        count = state["completed_steps"] + 1
        step = AgentStep(count, decision.thought, decision.action, decision.action_input,
                         observation.result, observation.error)
        return {"completed_steps": count, "history": [observation], "steps": [step],
                "next_node": "guard", "events": [event(state, "act", "guard", decision.action, count)]}

    def finish(state: AgentState):
        elapsed = state["elapsed_seconds"] if state["stop_reason"] == StopReason.TIMEOUT else clock() - state["started_at"]
        return {"elapsed_seconds": elapsed, "next_node": END,
                "events": [event(state, "finish", END, state["stop_reason"].value)]}

    def route(state: AgentState):
        return state["next_node"]

    builder = StateGraph(AgentState)
    for name, node in [("guard", guard), ("decide", decide), ("act", act), ("finish", finish)]:
        builder.add_node(name, node)
    builder.add_edge(START, "guard")
    builder.add_conditional_edges("guard", route, {"decide": "decide", "finish": "finish"})
    builder.add_conditional_edges("decide", route, {"act": "act", "finish": "finish"})
    builder.add_edge("act", "guard")
    builder.add_edge("finish", END)
    return builder.compile()


def run_agent(question: str, model: ReactModel | None = None, max_steps: int = 6,
              timeout_seconds: float = 10.0, clock: Callable[[], float] = time.monotonic) -> GraphRun:
    graph = build_graph(model, clock)
    state = initial_state(question, max_steps, timeout_seconds, clock())
    # Each tool iteration uses guard/decide/act plus terminal guard/decide/finish.
    # LangGraph's recursion guard must not pre-empt the observable Week 5 step limit.
    with tracing_context(enabled=False):
        result = graph.invoke(state, {"recursion_limit": 3 * max(0, max_steps) + 5})
    trace = AgentTrace(question, result["steps"], result["final_answer"],
                       result["stop_reason"], result["elapsed_seconds"])
    return GraphRun(trace, result)
