"""Enables `python -m tool_calling_lab` and the `tool-calling-lab` console script."""

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
