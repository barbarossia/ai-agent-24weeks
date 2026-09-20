"""Tests for the end-to-end function-calling loop (loop.run_once)."""

from tool_calling_lab.loop import run_once


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
