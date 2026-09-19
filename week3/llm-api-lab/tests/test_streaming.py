"""Streaming 与 SSE 解析的测试（成功 + 边界）。"""

from __future__ import annotations

import json

import pytest

from llm_api_lab.client import LLMClient
from llm_api_lab.errors import LlmRateLimitError
from llm_api_lab.messages import Conversation
from llm_api_lab.models import ChatRequest, ModelConfig, Usage
from llm_api_lab.providers import MockProvider, Script, ScriptedProvider
from llm_api_lab.transport import iter_sse_events


async def test_mock_stream_assembles_to_valid_json(
    conversation: Conversation, mock_provider: MockProvider
) -> None:
    client = LLMClient(mock_provider, config=ModelConfig(model="mock-llm-v1"))
    deltas = [delta async for delta in client.stream(conversation)]

    assert len(deltas) > 1
    assembled = "".join(deltas)
    assert json.loads(assembled)["category"] == "storage"


async def test_collect_stream_matches_stream_output(
    conversation: Conversation,
) -> None:
    client = LLMClient(MockProvider(chunk_size=5), config=ModelConfig(model="mock-llm-v1"))
    assembled = await client.collect_stream(conversation)
    assert json.loads(assembled)["action"] == "expand_or_clean_disk"


async def test_scripted_stream_emits_chunks_then_finish(
    conversation: Conversation,
) -> None:
    provider = ScriptedProvider(
        scripts=[
            Script(chunks=("a", "b"), usage=Usage(prompt_tokens=3, completion_tokens=2))
        ]
    )
    request = ChatRequest(model="mock-llm-v1", messages=tuple(conversation.messages))
    chunks = [chunk async for chunk in provider.stream(request)]

    assert [chunk.delta for chunk in chunks] == ["a", "b", ""]
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage == Usage(prompt_tokens=3, completion_tokens=2)


async def test_stream_propagates_retryable_error(conversation: Conversation) -> None:
    provider = ScriptedProvider(scripts=[Script(error=LlmRateLimitError("429"))])
    client = LLMClient(provider, config=ModelConfig(model="mock-llm-v1"))
    with pytest.raises(LlmRateLimitError):
        async for _ in client.stream(conversation):
            pass


def test_iter_sse_events_skips_noise_and_stops_at_done() -> None:
    lines = [
        ": keep-alive comment",
        "",
        'data: {"choices":[{"delta":{"content":"hello"}}]}',
        "event: message",  # 非 data 行：忽略
        'data: {"choices":[{"delta":{"content":" world"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"never"}}]}',
    ]
    events = list(iter_sse_events(lines))
    assert len(events) == 2
    assert events[0]["choices"][0]["delta"]["content"] == "hello"
    assert events[1]["choices"][0]["delta"]["content"] == " world"


def test_iter_sse_events_skips_malformed_json() -> None:
    lines = ["data: {not json}", 'data: {"ok": true}']
    events = list(iter_sse_events(lines))
    assert events == [{"ok": True}]
