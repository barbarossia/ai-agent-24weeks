"""Enables `python -m agent_loop_lab` and the `agent-loop-lab` console script."""

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
