from __future__ import annotations

import hashlib
import json

from .scenarios import FixtureScenario


def proposal_digest(scenario: FixtureScenario) -> str:
    canonical = json.dumps(
        {
            "case_id": scenario.case_id,
            "action_id": scenario.action_id,
            "description": scenario.action_description,
            "expected_effect": scenario.expected_effect,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
