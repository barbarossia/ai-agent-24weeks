"""HTTP API, health checks, bounded-cardinality metrics, and correlated traces."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import os
import time
from typing import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from .domain import TaskCommand, execute
from .storage import PostgresStore, TaskRecord, TaskStore


_tracing_configured = False


def configure_tracing() -> None:
    global _tracing_configured
    if _tracing_configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "week23-agent-api"}))
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, insecure=os.environ.get("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true")
        ))
    trace.set_tracer_provider(provider)
    _tracing_configured = True


def _task_body(record: TaskRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "operation": record.operation,
        "status": record.status,
        "input": record.input,
        "result": record.result,
        "trace_id": record.trace_id,
        "created_at": record.created_at.isoformat(),
    }


def create_app(store: TaskStore | None = None) -> FastAPI:
    configure_tracing()
    registry = CollectorRegistry()
    http_requests = Counter(
        "agent_http_requests_total", "HTTP requests served by the Week 23 lab API",
        ("method", "route", "status"), registry=registry,
    )
    http_duration = Histogram(
        "agent_http_request_duration_seconds", "HTTP request duration in seconds",
        ("method", "route"), registry=registry,
    )
    task_requests = Counter(
        "agent_task_requests_total", "Completed deterministic synthetic tasks",
        ("operation",), registry=registry,
    )
    logger = logging.getLogger("week23.api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.store is None:
            app.state.store = PostgresStore.from_environment()
        app.state.store.initialize()
        try:
            yield
        finally:
            provider = trace.get_tracer_provider()
            if isinstance(provider, TracerProvider):
                provider.force_flush(timeout_millis=3000)

    app = FastAPI(title="Week 23 Synthetic Agent API", lifespan=lifespan)
    app.state.store = store

    @app.middleware("http")
    async def telemetry(request: Request, call_next):
        started = time.perf_counter()
        parent = extract({"traceparent": request.headers.get("traceparent", "")})
        tracer = trace.get_tracer("week23.http")
        response: Response | None = None
        status_code = 500
        with tracer.start_as_current_span(
            "http.server", context=parent, kind=SpanKind.SERVER,
            attributes={"http.request.method": request.method, "url.path": request.url.path},
        ) as span:
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["X-Trace-Id"] = f"{span.get_span_context().trace_id:032x}"
                return response
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                elapsed = time.perf_counter() - started
                matched_route = request.scope.get("route")
                route = getattr(matched_route, "path", "unmatched")
                http_requests.labels(request.method, route, str(status_code)).inc()
                http_duration.labels(request.method, route).observe(elapsed)
                logger.info(json.dumps({
                    "event": "http_request",
                    "method": request.method,
                    "route": route,
                    "status": status_code,
                    "duration_ms": round(elapsed * 1000, 3),
                    "trace_id": f"{span.get_span_context().trace_id:032x}",
                }, separators=(",", ":")))

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(request: Request) -> dict[str, str]:
        if not request.app.state.store.ready():
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/tasks", status_code=201)
    def create_task(command: TaskCommand, request: Request) -> dict[str, object]:
        active_span = trace.get_current_span()
        trace_id = f"{active_span.get_span_context().trace_id:032x}"
        with trace.get_tracer("week23.agent").start_as_current_span(
            "agent.execute", attributes={"agent.operation": command.operation},
        ):
            result = execute(command)
            record = request.app.state.store.create(command, result, trace_id)
        task_requests.labels(command.operation).inc()
        return _task_body(record)

    @app.get("/v1/tasks/{task_id}")
    def get_task(task_id: UUID, request: Request) -> dict[str, object]:
        record = request.app.state.store.get(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="task not found")
        return _task_body(record)

    return app


app = create_app()
