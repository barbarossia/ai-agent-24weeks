"""Run one SDK-backed A2A service process on loopback."""
from __future__ import annotations

import argparse

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette

from .agents import SpecialistExecutor


def make_agent_card(role: str, base_url: str) -> AgentCard:
    if role != "specialist":
        raise ValueError(f"unknown agent role: {role}")
    return AgentCard(
        name="Week 22 Synthetic Specialist",
        description="Returns deterministic sample checks over A2A.",
        version="1.0.0",
        supported_interfaces=[AgentInterface(
            url=base_url,
            protocol_binding="JSONRPC",
            protocol_version="1.0",
        )],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["application/json"],
        skills=[AgentSkill(
            id="synthetic-checks",
            name="Synthetic checks",
            description="Checks fixed sample data and returns a JSON artifact.",
            tags=["demo", "deterministic"],
            examples=["Check the sample data."],
            input_modes=["text/plain"],
            output_modes=["application/json"],
        )],
    )


def build_app(role: str, base_url: str, specialist_url: str | None = None) -> Starlette:
    if role != "specialist":
        raise ValueError(f"unknown agent role: {role}")
    card = make_agent_card(role, base_url)
    handler = DefaultRequestHandler(
        agent_executor=SpecialistExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(routes=[
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, "/"),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Week 22 A2A service.")
    parser.add_argument("--role", choices=["specialist"], required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    base_url = f"http://{args.host}:{args.port}"
    app = build_app(args.role, base_url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
