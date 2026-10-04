"""Frozen clock for deterministic evaluation.

Week 12's ``homelab.py`` imports ``datetime`` as a module global
(``from datetime import datetime, timezone``) and calls
``datetime.now(timezone.utc)`` (homelab.py:43). Patching the module global at
runtime with a ``datetime`` subclass whose ``now`` accepts the **positional**
timezone argument (H004 carry-forward item 1) freezes both the MCP
``fetched_at`` and the answer's provenance line without editing Week 12.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

CLOCK_FROZEN_TO = datetime(2026, 1, 1, tzinfo=timezone.utc)
FROZEN_ISO = CLOCK_FROZEN_TO.isoformat()


class FrozenDatetime(datetime):
    """``datetime`` subclass returning a fixed instant, accepting ``now(tz)``."""

    @classmethod
    def now(cls, tz=None):  # noqa: D401 - signature must accept the positional tz
        return CLOCK_FROZEN_TO


@contextmanager
def freeze_homelab_clock():
    """Patch ``homelab_knowledge_agent.homelab.datetime`` for the context."""
    import homelab_knowledge_agent.homelab as homelab

    previous = homelab.datetime
    homelab.datetime = FrozenDatetime
    try:
        yield FrozenDatetime
    finally:
        homelab.datetime = previous
