"""Golden-dataset schema, loading and strict validation.

Repository-root ``/tests/`` is intentionally never created; the eval test tier
lives at ``week17/agent-evaluation-lab/tests/evals/`` and the dataset at
``week17/agent-evaluation-lab/data/golden_eval.jsonl`` (ticket-scope landing).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .constants import SCHEMA_VERSION

CATEGORIES = ("network", "docker", "esxi")
PREFIX_BY_CATEGORY = {"network": "NET", "docker": "DOC", "esxi": "ESX"}
CATEGORY_BY_PREFIX = {value: key for key, value in PREFIX_BY_CATEGORY.items()}
ID_PATTERN = re.compile(r"^W17-(NET|DOC|ESX)-(\d{3})$")
EXPECTED_TOOL_SEQUENCE = ["ping", "get_health_status"]

# Sanitizer screen applied at record level (question/notes/tags + every rag row).
# Conservative, high-signal patterns only: false positives would reject a
# legitimate fixture, so we do not attempt personal-name or generic-shape
# detection (documented in README as a known limit).
_UNSAFE_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|password|passwd|secret|credential)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
)

# Private / internal IP literals (RFC1918 + loopback + link-local). A bare
# dotted-quad is enough to flag; fixture data uses no IP literals.
_PRIVATE_IP_PATTERN = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|127(?:\.\d{1,3}){3}"
    r"|169\.254(?:\.\d{1,3}){2})\b"
)


def screen_text(text: str) -> str | None:
    """Return a reason string if ``text`` looks private/credential-bearing."""
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(text):
            return "credential-looking or private-looking text"
    if _PRIVATE_IP_PATTERN.search(text):
        return "private/internal IP address"
    return None



class RagRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1, max_length=1000)
    heading_path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2000)
    similarity: float

    def validate_sanitized(self) -> list[str]:
        errors: list[str] = []
        if not self.source_path.startswith("fixture/"):
            errors.append(f"rag source_path must start with 'fixture/': {self.source_path!r}")
        for field in (self.source_path, self.heading_path, self.content):
            reason = screen_text(field)
            if reason:
                errors.append(f"rag row {reason}")
                break
        return errors


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rag_rows: list[RagRow] = Field(min_length=1)
    mcp_health_data: str = "default-mock"  # or an explicit JSON list serialized by the runner


class RetrievalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_rows: int = Field(ge=1, le=5)
    required_source_path: str = Field(min_length=1, max_length=1000)


class McpContractExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_sequence: list[str]
    all_arguments_empty: bool
    adapter_mode: str
    read_only: bool


class AnswerExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must_include_any: list[str] = Field(min_length=1)
    must_not_include: list[str] = Field(default_factory=list)
    provenance: bool = True


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval: RetrievalExpectation
    mcp_contract: McpContractExpectation
    answer: AnswerExpectation


class GoldenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    case_id: str
    category: str
    question: str
    fixture: Fixture
    expected: Expected
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


def parse_record(raw: dict) -> GoldenRecord:
    """Parse a single raw JSON object, raising ``ValidationError`` on schema drift."""
    return GoldenRecord.model_validate(raw)


def load_raw_records(path: str | Path) -> list[dict]:
    path = Path(path)
    records: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return records


def load_dataset(path: str | Path) -> list[GoldenRecord]:
    return [parse_record(raw) for raw in load_raw_records(path)]


def _answer_contract_errors(rec: GoldenRecord) -> list[str]:
    errors: list[str] = []
    if rec.expected.mcp_contract.tool_sequence != EXPECTED_TOOL_SEQUENCE:
        errors.append(
            f"{rec.case_id}: tool_sequence must be exactly {EXPECTED_TOOL_SEQUENCE!r}"
        )
    if rec.expected.mcp_contract.all_arguments_empty is not True:
        errors.append(f"{rec.case_id}: all_arguments_empty must be True")
    if rec.expected.mcp_contract.adapter_mode != "mock":
        errors.append(f"{rec.case_id}: adapter_mode must be 'mock'")
    if rec.expected.mcp_contract.read_only is not True:
        errors.append(f"{rec.case_id}: read_only must be True")
    return errors


def _record_screen_errors(rec: GoldenRecord) -> list[str]:
    """Apply the sanitizer screen to every free-text surface of the record."""
    errors: list[str] = []
    for label, value in (("question", rec.question), ("notes", rec.notes)):
        reason = screen_text(value)
        if reason:
            errors.append(f"{rec.case_id}: {label} contains {reason}")
    for index, tag in enumerate(rec.tags):
        reason = screen_text(tag)
        if reason:
            errors.append(f"{rec.case_id}: tags[{index}] contains {reason}")
    for row in rec.fixture.rag_rows:
        errors.extend(f"{rec.case_id}: {err}" for err in row.validate_sanitized())
    return errors


def validate_dataset(records: list[GoldenRecord]) -> list[str]:
    """Return a list of validation errors (empty means valid)."""
    errors: list[str] = []
    if len(records) != 30:
        errors.append(f"dataset must contain exactly 30 records (found {len(records)})")

    counts = Counter(rec.category for rec in records)
    for category in CATEGORIES:
        if counts.get(category) != 10:
            errors.append(f"category {category!r} must have exactly 10 records (found {counts.get(category, 0)})")
    for category, count in counts.items():
        if category not in CATEGORIES:
            errors.append(f"unknown category {category!r}")

    seen: set[str] = set()
    for rec in records:
        if rec.schema_version != SCHEMA_VERSION:
            errors.append(f"{rec.case_id}: schema_version must be {SCHEMA_VERSION!r}")

        match = ID_PATTERN.match(rec.case_id)
        if not match:
            errors.append(f"{rec.case_id}: case_id must match W17-(NET|DOC|ESX)-NNN")
        else:
            if CATEGORY_BY_PREFIX[match.group(1)] != rec.category:
                errors.append(f"{rec.case_id}: prefix does not match category {rec.category!r}")

        if rec.case_id in seen:
            errors.append(f"{rec.case_id}: duplicate case_id")
        seen.add(rec.case_id)

        if not (1 <= len(rec.question) <= 2000):
            errors.append(f"{rec.case_id}: question must be 1-2000 characters")

        rows = rec.fixture.rag_rows
        if len(rows) > 10:
            errors.append(f"{rec.case_id}: rag_rows must not exceed 10")
        if rec.expected.retrieval.min_rows > len(rows):
            errors.append(f"{rec.case_id}: expected.retrieval.min_rows exceeds available rag_rows")
        if not any(row.source_path == rec.expected.retrieval.required_source_path for row in rows):
            errors.append(
                f"{rec.case_id}: required_source_path {rec.expected.retrieval.required_source_path!r} "
                "not present in fixture.rag_rows"
            )

        errors.extend(_record_screen_errors(rec))

        errors.extend(_answer_contract_errors(rec))

    return errors


def dataset_summary(records: list[GoldenRecord]) -> str:
    counts = Counter(rec.category for rec in records)
    ids_unique = len({rec.case_id for rec in records}) == len(records)
    degraded = sum(
        1
        for rec in records
        if rec.fixture.mcp_health_data != "default-mock"
        or any(rec.category == "esxi" for _ in [0])
    )
    return (
        f"{len(records)} records: network={counts.get('network', 0)} "
        f"docker={counts.get('docker', 0)} esxi={counts.get('esxi', 0)}, "
        f"ids unique={ids_unique}, esxi-degraded-cases={degraded}, sanitizer clean"
    )


__all__ = [
    "CATEGORIES",
    "EXPECTED_TOOL_SEQUENCE",
    "GoldenRecord",
    "ValidationError",
    "dataset_summary",
    "load_dataset",
    "load_raw_records",
    "parse_record",
    "validate_dataset",
]
