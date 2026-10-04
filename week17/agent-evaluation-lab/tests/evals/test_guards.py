"""Negative guard cases through the *real* agent/collect code paths."""

import asyncio

import pytest

from homelab_knowledge_agent.agent import KnowledgeAgent
from homelab_knowledge_agent.errors import IntegrationBlocked
from week17_agent_evaluation_lab.clock import FROZEN_ISO
from week17_agent_evaluation_lab.doubles import ScriptedGeneration, ScriptedRag


class _Homelab:
    def __init__(self, live):
        self._live = live

    async def collect(self):
        return self._live


def _agent(record, live):
    generation = ScriptedGeneration(record)
    return KnowledgeAgent(ScriptedRag(record), _Homelab(live), generation), generation


def test_non_mock_adapter_envelope_blocks_before_generate(records):
    rec = records[0]
    live = {"adapter": "Other", "fetched_at": FROZEN_ISO, "data": []}
    agent, generation = _agent(rec, live)
    with pytest.raises(IntegrationBlocked, match="MockAdapter"):
        asyncio.run(agent.answer(rec.question))
    assert generation.calls == []


def test_oversized_live_payload_blocks(records):
    rec = records[0]
    live = {"adapter": "MockAdapter", "fetched_at": FROZEN_ISO, "data": ["x" * 13000]}
    agent, _ = _agent(rec, live)
    with pytest.raises(IntegrationBlocked, match="12000"):
        asyncio.run(agent.answer(rec.question))


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_invalid_question_raises_value_error(records, question):
    rec = records[0]
    agent, _ = _agent(rec, {"adapter": "MockAdapter", "fetched_at": FROZEN_ISO, "data": []})
    with pytest.raises(ValueError):
        asyncio.run(agent.answer(question))
