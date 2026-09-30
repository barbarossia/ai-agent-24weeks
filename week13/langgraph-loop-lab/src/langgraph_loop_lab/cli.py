import argparse
import json

from agent_loop_lab.react_model import StubbornModel

from .graph import build_graph, run_agent


def display(question, **kwargs):
    result = run_agent(question, **kwargs)
    print(f"\nQuestion: {question}")
    for index, event in enumerate(result.events, 1):
        print(f"node[{index:02}] {event.node} -> {event.next_node} | "
              f"steps={event.completed_steps} history={event.history_size} | {event.detail}")
    for step in result.trace.steps:
        print(f"tool[{step.step_number}] {step.action} input={json.dumps(step.action_input)} "
              f"result={json.dumps(step.result)} error={step.error}")
    print(f"stop_reason={result.trace.stop_reason.value}")
    print(f"final_answer={result.trace.final_answer}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Week 5 mock agent as an explicit LangGraph StateGraph")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--diagram", action="store_true", help="Print Mermaid from the compiled graph; no image service")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--stubborn", action="store_true", help="Use Week 5's never-finished mock model")
    args = parser.parse_args(argv)
    if args.diagram:
        print(build_graph().get_graph().draw_mermaid())
    elif args.question:
        display(args.question, model=StubbornModel() if args.stubborn else None,
                max_steps=args.max_steps, timeout_seconds=args.timeout)
    else:
        for question in ["Diagnose host web01", "Diagnose host esxi01", "Diagnose host unknown99",
                         "Diagnose host buggy01", "What is the status of host db01?", "Tell me a joke"]:
            display(question)
        display("Diagnose host web01", model=StubbornModel(), max_steps=3)
        display("Diagnose host web01", timeout_seconds=0)
    return 0
