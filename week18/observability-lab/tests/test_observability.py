import json
import re
import pytest
from week18_observability_lab import DemoAgent, FaultPlan
from week18_observability_lab.tracing import Tracer

def test_parent_child_trace_and_no_payloads():
    agent = DemoAgent()
    assert agent.handle()["status"] == "success"
    spans = agent.tracer.spans
    req = spans[0]
    assert req.name == "request" and req.parent_span_id is None
    assert all(s.trace_id == req.trace_id for s in spans)
    assert spans[1].parent_span_id == req.span_id
    assert spans[2].parent_span_id == spans[1].span_id
    assert spans[3].parent_span_id == spans[1].span_id
    assert not any("prompt" in json.dumps(s.to_dict()).lower() for s in spans)
    assert [s.duration_ms for s in spans if s.name == "llm"] == [2.0]

def test_metrics_are_prometheus_and_labels_bounded():
    agent = DemoAgent(); agent.handle()
    text = agent.metrics.render()
    assert "agent_requests_total" in text and "agent_operation_duration_ms_bucket" in text
    assert 'operation="llm",status="success"' in text
    assert not re.search(r'(request_id|user_id|prompt|secret)=', text, re.I)
    with pytest.raises(ValueError): agent.metrics.observe("arbitrary-user-value", "success", 1)

def test_faults_deterministic_and_retry_observable():
    slow = DemoAgent(); assert slow.handle(fault="slow")["synthetic_latency_ms"] == 126
    assert next(s for s in slow.tracer.spans if s.name == "llm").duration_ms == 120.0
    retry = DemoAgent(); retry.handle(fault="retry")
    llm = [s for s in retry.tracer.spans if s.name == "llm"]
    assert len(llm) == 2 and [s.status for s in llm] == ["error", "ok"]
    assert llm[0].attributes["attempt"] == 1 and llm[1].attributes["attempt"] == 2
    failed = DemoAgent()
    with pytest.raises(RuntimeError): failed.handle(fault="failure")
    assert failed.tracer.spans[0].status == "error"

def test_fault_plan_rejects_unknown_mode():
    with pytest.raises(ValueError): FaultPlan("random")

def test_tracer_drops_unbounded_values_and_rejects_untrusted_span_names():
    tracer = Tracer()
    with tracer.span("request", operation="private prompt", fault={"secret": "value"},
                     user_id="sensitive", cost_usd=float("inf")) as span:
        pass
    assert span.attributes == {}
    serialized = json.dumps(span.to_dict())
    assert "private prompt" not in serialized and "sensitive" not in serialized
    with pytest.raises(ValueError):
        with tracer.span("user supplied prompt"):
            pass
