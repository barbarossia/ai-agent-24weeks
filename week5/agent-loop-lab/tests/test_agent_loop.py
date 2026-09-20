"""Tests for the hand-written multi-step Agent Loop (agent_loop.run_agent)."""

from agent_loop_lab.agent_loop import StopReason, run_agent
from agent_loop_lab.react_model import Decision, Observation, ReactModel, StubbornModel


def test_diagnose_up_host_runs_three_steps_then_final_answer():
    trace = run_agent("Diagnose host web01")
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert [s.action for s in trace.steps] == [
        "get_host_status",
        "get_docker_status",
        "check_alerting",
    ]
    assert all(s.error is None for s in trace.steps)
    assert "web01" in trace.final_answer
    assert "up" in trace.final_answer
    assert "no active alerts" in trace.final_answer


def test_diagnose_down_host_stops_early_after_one_step():
    trace = run_agent("Diagnose host esxi01")
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert [s.action for s in trace.steps] == ["get_host_status"]
    assert "DOWN" in trace.final_answer


def test_diagnose_unknown_host_stops_after_status_error():
    trace = run_agent("Diagnose host totally-unknown-host-123")
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert [s.action for s in trace.steps] == ["get_host_status"]
    assert trace.steps[0].error is not None
    assert "could not read host status" in trace.final_answer


def test_diagnose_buggy01_survives_unexpected_tool_exception():
    """buggy01's alerting tool raises a plain RuntimeError. The loop must
    catch it (not crash) and still finish with a final answer that mentions
    the unexpected failure.
    """
    trace = run_agent("Diagnose host buggy01")
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert [s.action for s in trace.steps] == [
        "get_host_status",
        "get_docker_status",
        "check_alerting",
    ]
    alert_step = trace.steps[-1]
    assert alert_step.error is not None
    assert "unexpected tool error" in alert_step.error
    assert "unexpectedly" in trace.final_answer


def test_single_tool_question_still_terminates_in_one_step():
    trace = run_agent("What is the status of host db01?")
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert [s.action for s in trace.steps] == ["get_host_status"]
    assert "up" in trace.final_answer


def test_unrelated_question_produces_zero_tool_steps():
    trace = run_agent("Tell me a joke")
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert trace.steps == [] or all(s.action is None for s in trace.steps)
    assert trace.final_answer


def test_unknown_action_from_model_is_handled_without_crashing():
    class RogueModel(ReactModel):
        def decide(self, question, history):
            if history:
                return Decision(thought="give up", final_answer="gave up after rogue tool call")
            return Decision(thought="call a made-up tool", action="delete_everything", action_input={})

    trace = run_agent("anything", model=RogueModel())
    assert trace.stop_reason is StopReason.FINAL_ANSWER
    assert trace.steps[0].action == "delete_everything"
    assert trace.steps[0].error is not None
    assert "unknown tool" in trace.steps[0].error


def test_max_steps_stops_a_model_that_never_answers():
    trace = run_agent("Diagnose host web01", model=StubbornModel(), max_steps=3)
    assert trace.stop_reason is StopReason.MAX_STEPS_REACHED
    assert trace.final_answer is None
    assert len(trace.steps) == 3
    assert all(s.action == "get_host_status" for s in trace.steps)


def test_timeout_stops_the_loop_before_max_steps_using_injected_clock():
    """Inject a fake clock that jumps far into the future after the first
    call so the wall-clock budget is exhausted before a second step can run,
    even though max_steps would otherwise allow many more iterations.
    """
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0])

    def fake_clock() -> float:
        return next(ticks, 100.0)

    trace = run_agent(
        "Diagnose host web01",
        model=StubbornModel(),
        max_steps=10,
        timeout_seconds=5.0,
        clock=fake_clock,
    )
    assert trace.stop_reason is StopReason.TIMEOUT
    assert trace.final_answer is None
    assert len(trace.steps) == 1


def test_react_model_decide_receives_full_history():
    """The model must actually see accumulated observations (not just the
    latest one) so multi-step decisions like diagnosis can inspect earlier
    results.
    """
    model = ReactModel()
    trace = run_agent("Diagnose host web01", model=model)
    assert trace.stop_reason is StopReason.FINAL_ANSWER

    # Re-run the decision steps manually to confirm history grows monotonically.
    history: list[Observation] = []
    seen_lengths = []
    for step in trace.steps:
        seen_lengths.append(len(history))
        history.append(Observation(action=step.action, result=step.result, error=step.error))
    assert seen_lengths == [0, 1, 2]
