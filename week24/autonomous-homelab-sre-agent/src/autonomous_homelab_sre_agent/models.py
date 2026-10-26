from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Incident(StrictModel):
    request_summary: str = Field(max_length=160)
    service: Literal["netflix"]
    domain: Literal["netflix.com"]
    case_id: str
    instruction_like_input: bool = False


class Citation(StrictModel):
    source: str
    heading: str
    line: int = Field(ge=1)
    excerpt: str = Field(max_length=400)
    source_id: str


class ToolObservation(StrictModel):
    tool: str
    evidence_id: str
    data: dict[str, Any]


class Diagnosis(StrictModel):
    cause_code: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]
    citations: tuple[Citation, ...]


class AgentHandoff(StrictModel):
    protocol: Literal["local-a2a/1"] = "local-a2a/1"
    task_id: str
    sender: str
    recipient: str
    diagnosis: Diagnosis
    evidence: tuple[ToolObservation, ...]


class ReviewResult(StrictModel):
    accepted: bool
    reviewer: str
    rationale: str
    corroborating_evidence: tuple[str, ...]
    citations: tuple[Citation, ...]


class FixProposal(StrictModel):
    action_id: str
    description: str
    expected_effect: str
    proposal_digest: str


class ApprovalDecision(StrictModel):
    decision: Literal["approve", "reject"]
    action_id: str
    proposal_digest: str
    approver: str = Field(min_length=1, max_length=80)


class SimulationResult(StrictModel):
    status: Literal["simulated"]
    action_id: str
    overlay: str
    audit_id: str
