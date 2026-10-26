from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from week23_production_lab.app import create_app
from week23_production_lab.domain import TaskCommand
from week23_production_lab.storage import TaskRecord


class MemoryStore:
    def __init__(self, ready: bool = True):
        self.is_ready = ready
        self.records: dict[UUID, TaskRecord] = {}

    def initialize(self) -> None:
        return None

    def ready(self) -> bool:
        return self.is_ready

    def create(self, command: TaskCommand, result: dict[str, object], trace_id: str) -> TaskRecord:
        record = TaskRecord(
            uuid4(), command.operation, "completed", command.input.model_dump(),
            result, trace_id, datetime.now(timezone.utc),
        )
        self.records[record.id] = record
        return record

    def get(self, task_id: UUID) -> TaskRecord | None:
        return self.records.get(task_id)


def test_task_round_trip_and_trace_context() -> None:
    trace_id = "0123456789abcdef0123456789abcdef"
    parent_span_id = "0123456789abcdef"
    with TestClient(create_app(MemoryStore())) as client:
        response = client.post(
            "/v1/tasks",
            json={"operation": "sum", "input": {"numbers": [2, 3, 5]}},
            headers={"traceparent": f"00-{trace_id}-{parent_span_id}-01"},
        )
        assert response.status_code == 201
        created = response.json()
        assert created["result"] == {"total": 10}
        assert created["trace_id"] == trace_id
        assert response.headers["x-trace-id"] == trace_id

        fetched = client.get(f"/v1/tasks/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["result"] == {"total": 10}


def test_readiness_fails_when_database_is_unavailable() -> None:
    with TestClient(create_app(MemoryStore(ready=False))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_task_input_rejects_unrecognized_fields() -> None:
    with TestClient(create_app(MemoryStore())) as client:
        response = client.post(
            "/v1/tasks",
            json={"operation": "echo", "input": {"message": "ok", "credential": "bad"}},
        )
        assert response.status_code == 422


def test_metrics_use_normalized_route_labels() -> None:
    with TestClient(create_app(MemoryStore())) as client:
        created = client.post(
            "/v1/tasks", json={"operation": "echo", "input": {"message": "metrics"}},
        ).json()
        fetched = client.get(f"/v1/tasks/{created['id']}")
        metrics = client.get("/metrics").text

    assert fetched.status_code == 200
    assert "agent_task_requests_total{operation=\"echo\"} 1.0" in metrics
    assert 'route="/v1/tasks/{task_id}"' in metrics
    assert f'route="/v1/tasks/{created["id"]}"' not in metrics
