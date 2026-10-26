from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Incident
from .scenarios import FixtureScenario


INSTRUCTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b", re.I),
    re.compile(r"\b(?:reveal|exfiltrate|print)\s+(?:the\s+)?(?:secret|credential|api key)\b", re.I),
    re.compile(r"\bcall\s+(?:the\s+)?write\s+tool\b", re.I),
    re.compile(r"\b(?:execute|run)\s+(?:this\s+)?(?:shell|command|script)\b", re.I),
)


def looks_instruction_like(text: str) -> bool:
    return any(pattern.search(text) for pattern in INSTRUCTION_PATTERNS)


@dataclass(frozen=True)
class RequestAssessment:
    incident: Incident
    untrusted_instruction_present: bool


def understand_request(request: str, scenario: FixtureScenario) -> RequestAssessment:
    if not isinstance(request, str) or not request.strip() or len(request) > 500:
        raise ValueError("request must be between 1 and 500 characters")
    if "netflix" not in request.casefold():
        raise ValueError("only the synthetic Netflix incident is supported")
    # Keep only a canonical summary in the graph state; raw instructions stay out of downstream nodes.
    flagged = looks_instruction_like(request)
    incident = Incident(
        request_summary="Netflix connectivity incident",
        service="netflix",
        domain="netflix.com",
        case_id=scenario.case_id,
        instruction_like_input=flagged,
    )
    return RequestAssessment(incident=incident, untrusted_instruction_present=flagged)


def bind_approval(decision: object, *, action_id: str, proposal_digest: str) -> dict[str, str]:
    """Validate a human reply against the exact proposal before any writer is launched."""
    from .models import ApprovalDecision

    approved = ApprovalDecision.model_validate(decision)
    if approved.action_id != action_id or approved.proposal_digest != proposal_digest:
        raise ValueError("approval does not match the pending proposal")
    return approved.model_dump(mode="json")
