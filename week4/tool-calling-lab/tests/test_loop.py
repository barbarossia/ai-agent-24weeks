"""Tests for the end-to-end function-calling loop (loop.run_once)."""

from tool_calling_lab.loop import run_once
from tool_calling_lab.mock_model import MockModel, ModelResponse, ToolCall


def test_host_status_question_calls_get_host_status():
    trace = run_once("What is the status of host web01?")
    assert trace.tool_call_name == "get_host_status"
    assert trace.tool_call_arguments == {"host": "web01"}
    assert trace.tool_error is None
    assert "up" in trace.final_answer


def test_docker_question_calls_get_docker_status():
    trace = run_once("Check docker containers on host db01")
    assert trace.tool_call_name == "get_docker_status"
    assert trace.tool_error is None
    assert "postgres" in trace.final_answer


def test_dns_question_calls_get_dns_result():
    trace = run_once("Resolve DNS for example.com")
    assert trace.tool_call_name == "get_dns_result"
    assert trace.tool_error is None
    assert "93.184.216.34" in trace.final_answer


def test_unknown_host_produces_tool_error_without_crashing():
    trace = run_once("What is the status of host gateway99?")
    assert trace.tool_call_name == "get_host_status"
    assert trace.tool_error is not None
    assert "gateway99" in trace.final_answer
    assert "failed" in trace.final_answer


def test_unrelated_question_gets_no_tool_call():
    trace = run_once("Tell me a joke")
    assert trace.tool_call_name is None
    assert trace.final_answer  # some direct response, no tool involved


def test_trace_records_all_five_steps_for_a_tool_call():
    trace = run_once("What is the status of host web01?")
    assert len(trace.steps) == 5
    assert trace.steps[0].startswith("1.")
    assert trace.steps[-1].startswith("5.")


def test_unknown_tool_produces_five_step_trace_with_dispatch_attempt():
    """Reviewer P2: an unregistered tool name from the model must still walk
    through step 3 (a recorded dispatch attempt) before the error-handling
    steps 4-5, so the trace is always five steps long, not four.
    """

    class RogueModel(MockModel):
        """A mock model that always names a tool the registry doesn't have."""

        def request(self, user_question, tool_definitions):  # noqa: D401
            return ModelResponse(tool_call=ToolCall(name="delete_everything", arguments={}))

    trace = run_once("anything", model=RogueModel())

    assert len(trace.steps) == 5
    assert [step.split(".", 1)[0] + "." for step in trace.steps] == ["1.", "2.", "3.", "4.", "5."]
    assert "unknown tool" in trace.steps[2]
    assert "delete_everything" in trace.steps[2]
    assert trace.tool_error is not None
    assert "delete_everything" in trace.final_answer


def test_model_request_receives_full_tool_definitions():
    """Reviewer P1: model.request must receive the generated JSON-Schema tool
    definitions themselves (names, descriptions, parameter schemas) rather
    than just a bare list of tool names.
    """
    model = MockModel()
    trace = run_once("What is the status of host web01?", model=model)

    assert model.last_tool_definitions == trace.tool_definitions
    assert len(model.last_tool_definitions) == 3

    names = {definition["function"]["name"] for definition in model.last_tool_definitions}
    assert names == {"get_host_status", "get_dns_result", "get_docker_status"}

    for definition in model.last_tool_definitions:
        assert definition["type"] == "function"
        function = definition["function"]
        assert isinstance(function["name"], str) and function["name"]
        assert isinstance(function["description"], str) and function["description"]
        assert "properties" in function["parameters"]
