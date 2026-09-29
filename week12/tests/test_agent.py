import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from homelab_knowledge_agent.agent import KnowledgeAgent
from homelab_knowledge_agent.context import Conversation
from homelab_knowledge_agent.errors import IntegrationBlocked


def parts():
    rag = Mock()
    rag.retrieve.return_value = [{"source_path": "fixture/runbook.md", "heading_path": "Storage > Space",
                                 "content": "Check datastore free space.", "similarity": 0.8}]
    mcp = Mock()
    mcp.collect = AsyncMock(return_value={"adapter": "MockAdapter", "fetched_at": "2026-09-29T00:00:00Z",
                                         "data": [{"status": "degraded", "reason": "low space"}]})
    model = Mock()
    model.generate = AsyncMock(return_value="The runbook's space check relates to the mock degraded datastore.")
    return rag, mcp, model


def test_both_sources_reach_synthesis_and_output_provenance():
    rag, mcp, model = parts()
    agent = KnowledgeAgent(rag, mcp, model)
    answer = asyncio.run(agent.answer("What should I check?"))
    prompt = model.generate.call_args.args[0]
    data = json.loads(prompt.split("\n", 1)[1])
    assert data["knowledge"][0]["content"] == "Check datastore free space."
    assert data["mcp_live_data"]["data"][0]["status"] == "degraded"
    assert "fixture/runbook.md — Storage > Space" in answer
    assert "MockAdapter" in answer and "not real HomeLab device readings" in answer
    assert agent.conversation.snapshot()[0]["question"] == "What should I check?"


def test_repeated_calls_have_bounded_history_and_fresh_evidence():
    rag, mcp, model = parts()
    agent = KnowledgeAgent(rag, mcp, model, Conversation(max_turns=2, max_chars=2000))
    for i in range(10):
        asyncio.run(agent.answer(f"question {i}"))
    payload = json.loads(model.generate.call_args.args[0].split("\n", 1)[1])
    assert [x["question"] for x in payload["recent_history"]] == ["question 7", "question 8"]
    assert len(agent.conversation.snapshot()) == 2
    assert rag.retrieve.call_count == mcp.collect.call_count == 10


def test_character_bound_drops_old_complete_exchanges():
    history = Conversation(max_turns=5, max_chars=12)
    history.remember("old", "12345")
    history.remember("new", "12345")
    assert history.snapshot() == [{"question": "new", "answer": "12345"}]
    history.remember("oversized", "x" * 20)
    assert history.snapshot() == []
    disabled = Conversation(max_turns=0)
    disabled.remember("q", "a")
    assert disabled.snapshot() == []


def test_empty_retrieval_is_explicit():
    rag, mcp, model = parts()
    rag.retrieve.return_value = []
    assert "No knowledge matches" in asyncio.run(KnowledgeAgent(rag, mcp, model).answer("health?"))


def test_failure_does_not_persist_history_or_call_later_sources():
    rag, mcp, model = parts()
    rag.retrieve.side_effect = IntegrationBlocked("Database absent")
    agent = KnowledgeAgent(rag, mcp, model)
    with pytest.raises(IntegrationBlocked):
        asyncio.run(agent.answer("health?"))
    mcp.collect.assert_not_called()
    model.generate.assert_not_called()
    assert agent.conversation.snapshot() == []


@pytest.mark.parametrize("question", ["", " ", "x" * 2001])
def test_invalid_questions(question):
    rag, mcp, model = parts()
    with pytest.raises(ValueError):
        asyncio.run(KnowledgeAgent(rag, mcp, model).answer(question))
    rag.retrieve.assert_not_called()


def test_reject_nonmock_or_oversized_evidence():
    rag, mcp, model = parts()
    for live in [{"adapter": "OpenWrtAdapter"}, {"adapter": "MockAdapter", "data": "x" * 12001}]:
        mcp.collect.return_value = live
        with pytest.raises(IntegrationBlocked):
            asyncio.run(KnowledgeAgent(rag, mcp, model).answer("health?"))
    model.generate.assert_not_called()
