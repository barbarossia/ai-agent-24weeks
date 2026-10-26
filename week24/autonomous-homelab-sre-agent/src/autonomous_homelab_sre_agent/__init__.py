"""Standalone Week 24 autonomous SRE lab with local deterministic fixtures."""

import os

# Restrict LangGraph checkpoint deserialization before any LangGraph module is imported.
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"

__version__ = "0.1.0"
