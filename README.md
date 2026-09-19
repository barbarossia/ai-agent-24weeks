# AI Agent Engineer — 24-Week Learning Repository

This repository contains a practical 24-week learning path for building AI-agent systems with Python. Each week turns one topic into a small, runnable, tested project rather than a collection of isolated notes.

It is the implementation workspace for the learning plan at `01-Projects/AI-Agent/AI-Agent-Engineer-24周学习计划`.

## Learning path

| Week | Focus | Project |
| --- | --- | --- |
| 1 | Python backend foundations | `ai-agent-lab`: typed HomeLab health-check CLI |
| 2 | Async Python and FastAPI | `homelab-api`: REST, SSE, and WebSocket API |
| 3 | LLM API fundamentals | `llm-api-lab`: streaming, structured output, retries, and provider boundaries |

The projects build on one another: Week 2 reuses the Week 1 domain layer, and Week 3 applies the same boundary-validation and reliability principles to model APIs.

## Repository structure

```text
week1/
├── ai-agent-lab/       # Typed CLI, Pydantic models, errors, pytest
├── notes/              # Week 1 learning notes
└── README.md
week2/
├── homelab-api/        # FastAPI service with async checks and events
├── notes/              # Week 2 learning notes
└── README.md
week3/
├── llm-api-lab/        # LLM client, streaming, schemas, retries, usage
├── notes/              # Week 3 learning notes
└── README.md
```

Each project has its own `pyproject.toml`, `uv.lock`, tests, examples, and detailed README.

## Quick start

Install [uv](https://docs.astral.sh/uv/) and Python 3.11, then choose a project:

```bash
cd week1/ai-agent-lab
uv sync
uv run pytest
uv run ai-agent-lab check-all
```

```bash
cd week2/homelab-api
uv sync
uv run pytest
uv run homelab-api
```

```bash
cd week3/llm-api-lab
uv sync
uv run pytest
uv run llm-api-lab demo
```

The Week 3 exercises use deterministic mock providers and do not require an API key or incur model costs.

## Development principles

- Use `uv` and lock files for reproducible environments.
- Validate data at boundaries with Pydantic.
- Keep domain logic separate from transport and framework code.
- Make failures observable and testable: timeouts, retries, invalid input, and malformed model output are all covered.
- Prefer deterministic local tests before connecting real external services.

See each week's README for architecture notes, command reference, exercises, and topics intentionally left for later practice.

## Language

The detailed learning notes and project documentation are primarily written in Chinese, with code and command examples kept in English.
