from __future__ import annotations

import argparse
import hmac
import os

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .models import SimulationResult
from .scenarios import get_scenario
from .workflow_policy import proposal_digest


def create_write_server(case_id: str, capability: str | None) -> MCPServer:
    scenario = get_scenario(case_id)
    server = MCPServer("week24-simulated-write-only")
    applied: SimulationResult | None = None

    @server.tool()
    def apply_simulated_remediation(action_id: str, digest: str, approval_capability: str) -> dict[str, str]:
        """Apply one approved action to the local in-memory fixture overlay only."""
        nonlocal applied
        if not capability or not hmac.compare_digest(approval_capability, capability):
            raise ToolError("approval capability required")
        if action_id != scenario.action_id or digest != proposal_digest(scenario):
            raise ToolError("action is not allowlisted for this scenario")
        if applied is None:
            audit_id = f"sim-{scenario.case_id}-{scenario.action_id}"
            applied = SimulationResult(
                status="simulated", action_id=action_id, overlay=action_id, audit_id=audit_id
            )
        return applied.model_dump(mode="json")

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    args = parser.parse_args(argv)
    capability = os.environ.get("W24_SIMULATED_WRITE_CAPABILITY")
    create_write_server(args.case, capability).run()


if __name__ == "__main__":
    main()
