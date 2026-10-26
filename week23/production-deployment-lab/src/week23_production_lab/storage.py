"""PostgreSQL-backed durable task records."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from opentelemetry import trace

from .domain import TaskCommand


@dataclass(frozen=True)
class TaskRecord:
    id: UUID
    operation: str
    status: str
    input: dict[str, object]
    result: dict[str, object]
    trace_id: str
    created_at: datetime


class TaskStore(Protocol):
    def initialize(self) -> None: ...
    def ready(self) -> bool: ...
    def create(self, command: TaskCommand, result: dict[str, object], trace_id: str) -> TaskRecord: ...
    def get(self, task_id: UUID) -> TaskRecord | None: ...


class PostgresStore:
    def __init__(self, *, host: str, database: str, user: str, password_file: str):
        self.host = host
        self.database = database
        self.user = user
        self.password_file = Path(password_file)

    @classmethod
    def from_environment(cls) -> "PostgresStore":
        return cls(
            host=os.environ.get("POSTGRES_HOST", "db"),
            database=os.environ.get("POSTGRES_DB", "week23"),
            user=os.environ.get("POSTGRES_USER", "week23"),
            password_file=os.environ.get("POSTGRES_PASSWORD_FILE", "/run/secrets/postgres_password"),
        )

    def _connect(self) -> psycopg.Connection:
        password = self.password_file.read_text(encoding="utf-8").strip()
        if not password:
            raise RuntimeError("database password secret is empty")
        return psycopg.connect(
            host=self.host,
            dbname=self.database,
            user=self.user,
            password=password,
            connect_timeout=3,
            application_name="week23-agent-api",
        )

    def initialize(self) -> None:
        with trace.get_tracer(__name__).start_as_current_span("postgres.initialize"):
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id UUID PRIMARY KEY,
                        operation TEXT NOT NULL CHECK (operation IN ('echo', 'sum')),
                        status TEXT NOT NULL CHECK (status = 'completed'),
                        task_input JSONB NOT NULL,
                        result JSONB NOT NULL,
                        trace_id CHAR(32) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )

    def ready(self) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1")
            return True
        except (OSError, psycopg.Error):
            return False

    def create(self, command: TaskCommand, result: dict[str, object], trace_id: str) -> TaskRecord:
        task_id = uuid4()
        task_input = command.input.model_dump()
        with trace.get_tracer(__name__).start_as_current_span("postgres.task.insert") as span:
            span.set_attribute("db.system", "postgresql")
            span.set_attribute("task.id", str(task_id))
            with self._connect() as connection:
                row = connection.execute(
                    """
                    INSERT INTO tasks (id, operation, status, task_input, result, trace_id)
                    VALUES (%s, %s, 'completed', %s, %s, %s)
                    RETURNING created_at
                    """,
                    (task_id, command.operation, Jsonb(task_input), Jsonb(result), trace_id),
                ).fetchone()
        assert row is not None
        return TaskRecord(task_id, command.operation, "completed", task_input, result, trace_id, row[0])

    def get(self, task_id: UUID) -> TaskRecord | None:
        with trace.get_tracer(__name__).start_as_current_span("postgres.task.select") as span:
            span.set_attribute("db.system", "postgresql")
            span.set_attribute("task.id", str(task_id))
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT id, operation, status, task_input, result, trace_id, created_at
                    FROM tasks WHERE id = %s
                    """,
                    (task_id,),
                ).fetchone()
        if row is None:
            return None
        return TaskRecord(*row[:5], row[5].strip(), row[6])
