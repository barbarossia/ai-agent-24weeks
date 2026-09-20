"""Tests for tool argument validation and mock tool execution."""

import pytest
from pydantic import ValidationError

from tool_calling_lab.tools import (
    TOOLS,
    ToolExecutionError,
    get_dns_result,
    get_docker_status,
    get_host_status,
)


def test_get_host_status_known_host():
    result = get_host_status("web01")
    assert result == {"host": "web01", "status": "up", "latency_ms": 12}


def test_get_host_status_unknown_host_raises():
    with pytest.raises(ToolExecutionError):
        get_host_status("does-not-exist")


def test_get_dns_result_known_domain():
    result = get_dns_result("example.com")
    assert result["resolved_ip"] == "93.184.216.34"


def test_get_dns_result_unknown_domain_raises():
    with pytest.raises(ToolExecutionError):
        get_dns_result("nowhere.invalid")


def test_get_docker_status_known_host():
    result = get_docker_status("db01")
    assert result["containers"] == [{"name": "postgres", "state": "running"}]


def test_tool_registry_has_three_tools():
    assert set(TOOLS.keys()) == {"get_host_status", "get_dns_result", "get_docker_status"}


def test_tool_definition_is_json_schema_shaped():
    definition = TOOLS["get_host_status"].definition()
    assert definition["type"] == "function"
    assert definition["function"]["name"] == "get_host_status"
    assert "host" in definition["function"]["parameters"]["properties"]


def test_tool_execute_validates_arguments_before_running():
    with pytest.raises(ValidationError):
        TOOLS["get_host_status"].execute({"host": ""})  # empty string violates min_length


def test_tool_execute_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        TOOLS["get_host_status"].execute({"host": "web01", "unexpected": "x"})


def test_tool_execute_runs_the_backend():
    result = TOOLS["get_docker_status"].execute({"host": "web01"})
    assert result["host"] == "web01"
    assert len(result["containers"]) == 2
